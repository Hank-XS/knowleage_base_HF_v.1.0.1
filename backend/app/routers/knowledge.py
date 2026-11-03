"""知识库管理 REST：列表 / 上传 / 切片 / 版本对比 / 代码映射。"""
from __future__ import annotations

import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..deps import audit, current_user, require_roles
from ..db import User
from ..knowledge import manage as km
from ..knowledge import catalog
from ..ingest.documents import MAX_DOCUMENT
from ..response import KbError, ok

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _readable_doc(doc_id: str, user: User = Depends(current_user)):
    from ..knowledge.access import readable_document
    readable_document(doc_id, user)


@router.get('/catalog')
def catalog_options(request: Request, kb: str = '', project: str = '', user: User = Depends(current_user)):
    return ok(catalog.catalog_options(kb, project), request)


@router.get('/assets')
def assets(request: Request, kb: str = '', project: str = '', asset_type: str = '', purpose: str = '',
           tag: str = '', keyword: str = '', history: bool = False, version: str = '',
           page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
           user: User = Depends(current_user)):
    return ok(catalog.list_assets(kb, project, asset_type, purpose, tag, keyword, history, version, page, page_size), request)


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
    key: str = ''
    title: str = ""
    parent_key: str = ""


@router.post("/libraries")
def create_library(body: LibraryIn, request: Request,
                   user: User = Depends(require_roles("gov", "admin", "dev"))):
    try:
        key = body.key.strip() or f'sys-{uuid.uuid4().hex[:12]}'
        row = km.create_library(key, body.title or key, body.parent_key)
    except ValueError as e:
        raise KbError("40001", str(e))
    audit(request, user.username, "knowledge_library_create", row['key'])
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
    project: str = '', project_job: str = '', purpose: str = '', tag: str = '', history: bool = False, asset_type: str = '',
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
        project=project, project_job=project_job, purpose=purpose, tag=tag, history=history, asset_type=asset_type,
        page=page,
        page_size=page_size,
    )
    return ok(data, request)


@router.get("/docs/{doc_id}", dependencies=[Depends(_readable_doc)])
def get_doc(doc_id: str, request: Request, user: User = Depends(current_user)):
    doc = km.get_doc(doc_id, with_content=True)
    if not doc:
        raise KbError("40401", "文档不存在")
    return ok(doc, request)


@router.delete("/docs/{doc_id}", dependencies=[Depends(_readable_doc)])
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
    library_key: str = Form(""),
    version: str = Form(...),
    security: str = Form("public"),
    author: str = Form(""),
    tags: str = Form("[]"),
    official: bool = Form(True),
    auto_chunk: bool = Form(True),
    project: str = Form(''),
    purpose: str = Form('reference'),
    user: User = Depends(require_roles("gov", "admin", "dev")),
):
    content = await file.read(MAX_DOCUMENT + 1)
    if not content:
        raise KbError("40001", "上传文件为空")
    if (file.filename or '').lower().endswith('.zip'):
        raise KbError('40001', '工程 ZIP 请使用上传资料中的“代码工程 ZIP”入口')
    try:
        tag_list = json.loads(tags) if tags else []
        if not isinstance(tag_list, list):
            raise KbError('40001', '标签必须是文本列表')
    except json.JSONDecodeError:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        doc = await run_in_threadpool(km.upload_document,
            filename=file.filename or "upload.bin",
            content=content,
            library_key=library_key,
            version=version,
            security=security,
            author=author or user.username,
            tags=tag_list,
            official=official,
            auto_chunk=auto_chunk,
            project=project, purpose=purpose,
        )
    except ValueError as e:
        raise KbError("40001", str(e))
    audit(request, user.username, "knowledge_upload", doc["id"],
          detail={"name": doc["name"], "version": version})
    return ok(doc, request)


@router.get('/docs/{doc_id}/original', dependencies=[Depends(_readable_doc)])
def original(doc_id: str, version: str = '', user: User = Depends(current_user)):
    from ..db import SessionLocal, KbDocument, KbDocVersion
    from ..stores.objects import object_store
    from fastapi.responses import Response
    from urllib.parse import quote
    from pathlib import Path
    with SessionLocal() as db:
        doc = db.get(KbDocument, doc_id)
        if doc is None:
            raise KbError('40401', '资料不存在')
        row = db.query(KbDocVersion).filter_by(doc_id=doc_id, version=version or doc.version).one_or_none()
        key = (row.object_key if row else '') or (doc.object_key if not version or version == doc.version else '')
        if not key or not object_store.exists(key):
            raise KbError('40401', '原始文件不存在')
        filename = Path(key).name
        return Response((object_store._root / key).read_bytes(), media_type='application/octet-stream',
                        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename)})


@router.get("/docs/{doc_id}/chunks", dependencies=[Depends(_readable_doc)])
def get_chunks(doc_id: str, request: Request,
               version: str = "", keyword: str = "",
               user: User = Depends(current_user)):
    data = km.list_chunks(doc_id, version=version, keyword=keyword)
    if data.get("doc") is None:
        raise KbError("40401", "文档不存在")
    return ok(data, request)


@router.get("/docs/{doc_id}/versions", dependencies=[Depends(_readable_doc)])
def get_versions(doc_id: str, request: Request, user: User = Depends(current_user)):
    if not km.get_doc(doc_id, with_content=False):
        raise KbError("40401", "文档不存在")
    return ok(km.list_versions(doc_id), request)


@router.get("/docs/{doc_id}/diff", dependencies=[Depends(_readable_doc)])
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
def get_codemap(doc_id: str, request: Request, direction: str = 'code2doc', version_id: str = '', user: User = Depends(current_user)):
    from ..knowledge.browsing import code_map
    try:
        if direction not in {'code2doc', 'doc2code'}:
            raise ValueError('无效的映射方向')
        return ok(code_map(doc_id, direction, version_id), request)
    except ValueError as exc:
        raise KbError('40001', str(exc)) from exc


@router.get('/project-versions')
def get_project_versions(request: Request, library: str = '', project: str = '', user: User = Depends(current_user)):
    from ..knowledge.browsing import project_versions
    return ok(project_versions(library, project), request)


@router.get('/docs/{doc_id}/comparison-versions')
def get_comparison_versions(doc_id: str, request: Request, user: User = Depends(current_user)):
    from ..knowledge.browsing import comparison_versions
    try:
        return ok(comparison_versions(doc_id), request)
    except ValueError as exc:
        raise KbError('40001', str(exc)) from exc


@router.get('/docs/{doc_id}/comparison')
def get_comparison(doc_id: str, request: Request, old: str, new: str, user: User = Depends(current_user)):
    from ..knowledge.browsing import compare
    try:
        return ok(compare(doc_id, old, new), request)
    except ValueError as exc:
        raise KbError('40001', str(exc)) from exc


class CleanupIn(BaseModel):
    target: Literal['chunks', 'graph']
    doc_id: str = ''
    job_id: str = ''
    library: str = ''
    project: str = ''
    version: str = ''
    chunk_ids: list[str] = Field(default_factory=list, max_length=1000)
    confirmation_token: str = ''


@router.post('/cleanup/preview')
def preview_cleanup(body: CleanupIn, request: Request, user: User = Depends(require_roles('gov', 'admin', 'dev'))):
    from ..knowledge.maintenance import preview
    try:
        return ok(preview(body.model_dump(exclude={'confirmation_token'})), request)
    except ValueError as exc:
        raise KbError('40001', str(exc)) from exc


@router.post('/cleanup/execute')
def execute_cleanup(body: CleanupIn, request: Request, user: User = Depends(require_roles('gov', 'admin', 'dev'))):
    from ..knowledge.maintenance import execute
    try:
        result = execute(body.model_dump(exclude={'confirmation_token'}), body.confirmation_token)
    except ValueError as exc:
        raise KbError('40001', str(exc)) from exc
    audit(request, user.username, 'knowledge_cleanup_' + body.target, body.doc_id or body.job_id,
          detail={'title': result['title'], 'counts': result['counts']})
    return ok(result, request)
