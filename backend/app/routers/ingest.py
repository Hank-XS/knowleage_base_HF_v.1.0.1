"""知识接入路由：上传 → 六步流水线（parse→clean→tag→review→merge→index）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import IngestJob, SessionLocal, User
from ..deps import audit, current_user, require_roles
from ..ingest.clean import (
    default_dataset_root,
    import_cleaned_to_stores,
    load_jsonl,
    load_manifest,
)
from ..ingest.pipeline import create_job, run_dataset_clean_job, run_job
from ..response import KbError, ok
from ..stores.objects import object_store

router = APIRouter(prefix="/ingest", tags=["ingest"])

SOURCE_TYPES = ("error_code_table", "mapping", "message_format", "doc", "cobol")


@router.post("/jobs")
async def create_ingest_job(request: Request,
                            file: UploadFile = File(...),
                            source_type: str = Form(...),
                            user: User = Depends(require_roles("gov", "admin", "dev"))):
    if source_type not in SOURCE_TYPES:
        raise KbError("40001", f"source_type 必须是 {SOURCE_TYPES} 之一")
    content = await file.read()
    if not content:
        raise KbError("40001", "上传文件为空")
    key = object_store.inbox(source_type, file.filename or "upload.bin")
    object_store.put(key, content)
    job_id = create_job(source_type, [key], {"filename": file.filename})
    try:
        run_job(job_id)
    except Exception as e:
        raise KbError("50005", str(e)[:300])
    audit(request, user.username, "ingest_job", job_id, detail={"source_type": source_type})
    return _job_payload(job_id, request)


class CleanRunIn(BaseModel):
    do_import: bool = False
    include_tier_c: bool = False


@router.post("/clean/run")
def run_clean(body: CleanRunIn, request: Request,
              user: User = Depends(require_roles("gov", "admin", "dev"))):
    """全量数据集清洗（hf_data → 08_cleaned）。"""
    root = default_dataset_root()
    if not root.exists():
        raise KbError("40401", f"数据集根目录不存在：{root}")
    try:
        result = run_dataset_clean_job(do_import=body.do_import,
                                       include_tier_c=body.include_tier_c)
    except Exception as e:
        raise KbError("50005", f"清洗失败：{str(e)[:300]}")
    audit(request, user.username, "dataset_clean", result.get("job_id"),
          detail={"kg": result["clean"]["kg_triples"],
                  "chunks": result["clean"]["vector_chunks"],
                  "quarantine": result["clean"]["quarantine"]})
    return ok(result, request)


class CleanImportIn(BaseModel):
    include_tier_c: bool = False
    min_trust: float = Field(0.0, ge=0.0, le=1.0)


@router.post("/clean/import")
def import_clean(body: CleanImportIn, request: Request,
                 user: User = Depends(require_roles("gov", "admin", "dev"))):
    """将已有清洗产物导入图谱/向量（跳过 quarantine 与 pending_review 边）。"""
    try:
        stats = import_cleaned_to_stores(
            include_tier_c=body.include_tier_c, min_trust=body.min_trust)
    except FileNotFoundError as e:
        raise KbError("40401", str(e))
    except Exception as e:
        raise KbError("50005", f"导入失败：{str(e)[:300]}")
    audit(request, user.username, "clean_import", detail=stats)
    return ok(stats, request)


@router.get("/clean/manifest")
def get_clean_manifest(request: Request, user: User = Depends(current_user)):
    root = default_dataset_root()
    mf = load_manifest()
    if not mf:
        return ok({
            "exists": False,
            "dataset_root": str(root),
            "root": str(root),
            "out_dir": str(root / "08_cleaned"),
        }, request)
    payload = {k: v for k, v in mf.items() if k != "input_digest"}
    payload.update({
        "exists": True,
        "dataset_root": payload.get("root") or str(root),
        "input_digest_count": len(mf.get("input_digest") or {}),
    })
    return ok(payload, request)


@router.get("/clean/quarantine")
def list_quarantine(request: Request, limit: int = Query(50, ge=1, le=200),
                    user: User = Depends(current_user)):
    root = default_dataset_root() / "08_cleaned"
    rows = load_jsonl(root / "quarantine.jsonl", limit=limit)
    return ok({"total": len(rows), "items": rows}, request)


@router.get("/clean/conflicts")
def list_conflicts(request: Request, limit: int = Query(50, ge=1, le=200),
                   user: User = Depends(current_user)):
    root = default_dataset_root() / "08_cleaned"
    rows = load_jsonl(root / "conflict_ledger.jsonl", limit=limit)
    return ok({"total": len(rows), "items": rows}, request)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        job = db.get(IngestJob, job_id)
    if job is None:
        raise KbError("40401", "任务不存在")
    return _job_payload(job_id, request, job)


def _job_payload(job_id: str, request: Request, job: IngestJob | None = None):
    if job is None:
        with SessionLocal() as db:
            job = db.get(IngestJob, job_id)
    if job is None:
        raise KbError("40401", "任务不存在")
    return ok({"job_id": job.id, "source_type": job.source_type,
               "object_keys": job.object_keys, "steps": job.steps,
               "status": job.status, "error": job.error}, request)


@router.get("/jobs")
def list_jobs(request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        rows = db.execute(select(IngestJob).order_by(IngestJob.created_at.desc()).limit(50)).scalars().all()
    return ok([{"job_id": j.id, "source_type": j.source_type, "status": j.status,
                "object_keys": j.object_keys, "created_at": j.created_at.isoformat()} for j in rows], request)
