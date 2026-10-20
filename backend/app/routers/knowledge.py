"""知识库管理 REST：列表 / 上传 / 切片 / 版本对比 / 代码映射。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field

from ..deps import audit, current_user, require_roles
from ..db import User
from ..knowledge import manage as km
from ..response import KbError, ok

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/sync")
def sync_dataset(request: Request, force: bool = False,
                 user: User = Depends(require_roles("gov", "admin", "dev"))):
    result = km.sync_from_dataset(force=force)
    audit(request, user.username, "knowledge_sync", detail=result)
    return ok(result, request)


@router.get("/libraries")
def get_libraries(request: Request, user: User = Depends(current_user)):
    return ok(km.library_tree(), request)


class LibraryIn(BaseModel):
    key: str
    title: str = ""
    parent_key: str = ""


@router.post("/libraries")
def create_library(body: LibraryIn, request: Request,
                   user: User = Depends(require_roles("gov", "admin", "dev"))):
    try:
        row = km.create_library(body.key, body.title or body.key, body.parent_key)
    except ValueError as e:
        raise KbError("40001", str(e))
    audit(request, user.username, "knowledge_library_create", body.key)
    return ok(row, request)


@router.get("/docs")
def get_docs(
    request: Request,
    kb: str = Query("", description="知识库 key，如 01_tech_docs 或 02_code_assets/cobol"),
    keyword: str = "",
    doc_type: str = Query("", alias="type"),
    status: str = "",
    version: str = "",
    vectorized: str = Query("", description="yes|no|空"),
    official: str = Query("", description="yes|no|空"),
    security: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(current_user),
):
    data = km.list_docs(
        kb=kb,
        keyword=keyword,
        doc_type=doc_type,
        status=status,
        version=version,
        vectorized=vectorized,
        official=official,
        security=security,
        page=page,
        page_size=page_size,
    )
    return ok(data, request)


@router.get("/docs/{doc_id}")
def get_doc(doc_id: str, request: Request, user: User = Depends(current_user)):
    doc = km.get_doc(doc_id, with_content=True)
    if not doc:
        raise KbError("40401", "文档不存在")
    return ok(doc, request)


@router.delete("/docs/{doc_id}")
def remove_doc(doc_id: str, request: Request,
               user: User = Depends(require_roles("gov", "admin", "dev"))):
    if not km.delete_doc(doc_id):
        raise KbError("40401", "文档不存在")
    audit(request, user.username, "knowledge_doc_delete", doc_id)
    return ok({"deleted": True, "id": doc_id}, request)


class BatchStatusIn(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)
    status: str = Field(..., description="draft|review|published")
    action: str = Field("audit", description="submit|audit")


@router.post("/docs/batch-status")
def batch_status(body: BatchStatusIn, request: Request,
                 user: User = Depends(require_roles("gov", "admin", "biz", "dev"))):
    status = body.status
    if body.action == "submit":
        status = "review"
    try:
        n = km.batch_update_status(body.doc_ids, status)
    except ValueError as e:
        raise KbError("40001", str(e))
    audit(request, user.username, "knowledge_batch_status",
          detail={"count": n, "status": status, "action": body.action})
    return ok({"updated": n, "status": status}, request)


@router.post("/upload")
async def upload_doc(
    request: Request,
    file: UploadFile = File(...),
    library_key: str = Form("uploads"),
    version: str = Form(...),
    security: str = Form("public"),
    author: str = Form("admin"),
    tags: str = Form("[]"),
    official: bool = Form(True),
    auto_chunk: bool = Form(True),
    user: User = Depends(require_roles("gov", "admin", "dev")),
):
    content = await file.read()
    if not content:
        raise KbError("40001", "上传文件为空")
    try:
        tag_list = json.loads(tags) if tags else []
        if not isinstance(tag_list, list):
            tag_list = []
    except json.JSONDecodeError:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        doc = km.upload_document(
            filename=file.filename or "upload.bin",
            content=content,
            library_key=library_key,
            version=version,
            security=security,
            author=author or user.username,
            tags=tag_list,
            official=official,
            auto_chunk=auto_chunk,
        )
    except ValueError as e:
        raise KbError("40001", str(e))
    audit(request, user.username, "knowledge_upload", doc["id"],
          detail={"name": doc["name"], "version": version})
    return ok(doc, request)


@router.get("/docs/{doc_id}/chunks")
def get_chunks(doc_id: str, request: Request,
               version: str = "", keyword: str = "",
               user: User = Depends(current_user)):
    data = km.list_chunks(doc_id, version=version, keyword=keyword)
    if data.get("doc") is None:
        raise KbError("40401", "文档不存在")
    return ok(data, request)


@router.get("/docs/{doc_id}/versions")
def get_versions(doc_id: str, request: Request, user: User = Depends(current_user)):
    if not km.get_doc(doc_id, with_content=False):
        raise KbError("40401", "文档不存在")
    return ok(km.list_versions(doc_id), request)


@router.get("/docs/{doc_id}/diff")
def get_diff(doc_id: str, request: Request,
             old: str = Query(...), new: str = Query(...),
             user: User = Depends(current_user)):
    data = km.diff_versions(doc_id, old, new)
    if data.get("error") == "not_found":
        raise KbError("40401", "文档不存在")
    return ok(data, request)


class BumpVersionIn(BaseModel):
    new_version: str
    note: str = "内容更新"


@router.post("/docs/{doc_id}/versions")
def bump_version(doc_id: str, body: BumpVersionIn, request: Request,
                 user: User = Depends(require_roles("gov", "admin", "dev"))):
    try:
        doc = km.bump_demo_version(doc_id, body.new_version, body.note)
    except ValueError:
        raise KbError("40401", "文档不存在")
    audit(request, user.username, "knowledge_bump_version", doc_id,
          detail={"version": body.new_version})
    return ok(doc, request)


@router.get("/codemap")
def get_codemap_list(request: Request, kb: str = "",
                     user: User = Depends(current_user)):
    return ok(km.list_code_files(kb=kb), request)


@router.get("/codemap/{doc_id}")
def get_codemap(doc_id: str, request: Request, user: User = Depends(current_user)):
    data = km.code_map(doc_id)
    if data.get("error") == "not_found":
        raise KbError("40401", "代码文件不存在")
    return ok(data, request)
