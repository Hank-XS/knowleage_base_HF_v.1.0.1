"""治理工作台路由：打标任务 / 校对提交 / 标签词表 / 交叉打标触发。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import GovernTask, LabelVocab, SessionLocal, User
from ..deps import audit, require_roles
from ..ingest.pipeline import apply_tag_review
from ..ingest.tagger import ensure_vocab, get_vocab
from ..response import KbError, ok

router = APIRouter(prefix="/governance", tags=["governance"])


def _task_dict(t: GovernTask) -> dict:
    return {
        "id": t.id,
        "task_type": t.task_type,
        "title": t.title,
        "status": t.status,
        "items": t.items_json,
        "operator": t.operator,
        "created_at": t.created_at.isoformat(),
    }


@router.get("/tagging-tasks")
def list_tasks(request: Request, status: str | None = Query(None),
               limit: int = Query(500, ge=1, le=2000),
               user: User = Depends(require_roles("gov", "admin", "biz", "arch"))):
    with SessionLocal() as db:
        base = select(GovernTask)
        count_q = select(func.count()).select_from(GovernTask)
        if status:
            base = base.where(GovernTask.status == status)
            count_q = count_q.where(GovernTask.status == status)
        total = db.execute(count_q).scalar() or 0
        pending_total = db.execute(
            select(func.count()).select_from(GovernTask).where(GovernTask.status == "pending")
        ).scalar() or 0
        rows = db.execute(
            base.order_by(GovernTask.created_at.desc()).limit(limit)
        ).scalars().all()
    return ok({
        "items": [_task_dict(t) for t in rows],
        "total": total,
        "pending_total": pending_total,
        "limit": limit,
    }, request)


@router.get("/tagging-tasks/{task_id}")
def get_task(task_id: str, request: Request, user: User = Depends(require_roles("gov", "admin", "biz", "arch"))):
    with SessionLocal() as db:
        t = db.get(GovernTask, task_id)
    if t is None:
        raise KbError("40401", "任务不存在")
    return ok({"id": t.id, "task_type": t.task_type, "title": t.title,
               "status": t.status, "items": t.items_json, "operator": t.operator}, request)


class ReviewItemIn(BaseModel):
    item_id: str
    action: str  # accept / modify / reject
    tag: dict | None = None
    reason: str = ""


class TaskReviewIn(BaseModel):
    items: list[ReviewItemIn]
    operator: str = ""


@router.put("/tagging-tasks/{task_id}")
def submit_review(task_id: str, body: TaskReviewIn, request: Request,
                  user: User = Depends(require_roles("gov", "admin", "biz", "arch"))):
    if not body.items:
        raise KbError("40001", "items 不能为空")
    result = apply_tag_review(task_id, [i.model_dump() for i in body.items], user.username)
    audit(request, user.username, "tag_review", task_id, detail=result)
    return ok(result, request)


class BatchReviewIn(BaseModel):
    action: str = Field(..., description="accept / reject")
    task_ids: list[str] = Field(default_factory=list)
    all_pending: bool = False
    reason: str = ""


@router.post("/tagging-tasks/batch-review")
def batch_review(body: BatchReviewIn, request: Request,
                 user: User = Depends(require_roles("gov", "admin", "biz", "arch"))):
    """批量通过/驳回：按 task_ids，或 all_pending=true 处理全部待校对。"""
    action = (body.action or "").strip().lower()
    if action not in ("accept", "reject"):
        raise KbError("40001", "action 必须是 accept 或 reject")
    if not body.all_pending and not body.task_ids:
        raise KbError("40001", "请提供 task_ids 或设置 all_pending=true")

    with SessionLocal() as db:
        if body.all_pending:
            rows = db.execute(
                select(GovernTask).where(GovernTask.status == "pending")
            ).scalars().all()
        else:
            rows = db.execute(
                select(GovernTask).where(GovernTask.id.in_(body.task_ids))
            ).scalars().all()
        jobs = [(t.id, list(t.items_json or [])) for t in rows if t.status == "pending"]

    applied = rejected = processed = 0
    errors: list[dict] = []
    reason = body.reason or (
        "治理工作台批量驳回" if action == "reject" else ""
    )
    for tid, items in jobs:
        review_items = [
            {"item_id": it.get("item_id"), "action": action, "reason": reason}
            for it in items
            if it.get("item_id")
        ]
        if not review_items:
            errors.append({"task_id": tid, "error": "无有效条目"})
            continue
        try:
            result = apply_tag_review(tid, review_items, user.username)
            processed += 1
            applied += int(result.get("applied") or 0)
            rejected += int(result.get("rejected") or 0)
        except Exception as exc:  # noqa: BLE001 — 批量继续，汇总错误
            errors.append({"task_id": tid, "error": str(exc)})

    with SessionLocal() as db:
        remaining = db.execute(
            select(func.count()).select_from(GovernTask).where(GovernTask.status == "pending")
        ).scalar() or 0

    payload = {
        "processed": processed,
        "applied": applied,
        "rejected": rejected,
        "remaining_pending": remaining,
        "errors": errors[:20],
    }
    audit(request, user.username, "tag_review_batch", detail=payload)
    return ok(payload, request)


# ---------------------------------------------------------------- 标签词表
@router.get("/vocab")
def list_vocab(request: Request, status: str | None = Query(None),
               user: User = Depends(require_roles("gov", "admin", "biz", "arch"))):
    ensure_vocab()
    with SessionLocal() as db:
        q = select(LabelVocab).order_by(LabelVocab.category, LabelVocab.id)
        if status:
            q = q.where(LabelVocab.status == status)
        rows = db.execute(q).scalars().all()
    return ok([{"id": r.id, "category": r.category, "value": r.value,
                "status": r.status, "created_by": r.created_by} for r in rows], request)


class VocabIn(BaseModel):
    category: str
    value: str
    status: str = "candidate"   # candidate / approved


@router.post("/vocab")
def add_vocab(body: VocabIn, request: Request,
              user: User = Depends(require_roles("gov", "admin", "biz", "arch"))):
    if not body.value.strip():
        raise KbError("40001", "value 不能为空")
    with SessionLocal() as db:
        exists = db.execute(select(LabelVocab).where(
            LabelVocab.category == body.category,
            LabelVocab.value == body.value.strip())).scalar_one_or_none()
        if exists:
            raise KbError("40901", "词表已存在同名标签")
        row = LabelVocab(category=body.category, value=body.value.strip(),
                         status=("approved" if user.role in ("gov", "admin") else body.status),
                         created_by=user.username)
        db.add(row)
        db.commit()
        audit(request, user.username, "vocab_add", f"{body.category}:{body.value}")
        return ok({"id": row.id, "status": row.status}, request)


@router.put("/vocab/{vocab_id}")
def review_vocab(vocab_id: int, request: Request,
                 body: dict = None, user: User = Depends(require_roles("gov", "admin"))):
    action = (body or {}).get("action", "approve")   # approve / reject
    with SessionLocal() as db:
        row = db.get(LabelVocab, vocab_id)
        if row is None:
            raise KbError("40401", "词表项不存在")
        row.status = "approved" if action == "approve" else "rejected"
        db.commit()
    audit(request, user.username, "vocab_review", str(vocab_id), detail={"action": action})
    return ok({"id": vocab_id, "status": row.status}, request)


# ---------------------------------------------------------------- 交叉打标
@router.post("/cross-tag")
def trigger_cross_tag(request: Request, limit: int = 8,
                      user: User = Depends(require_roles("gov", "admin", "dev"))):
    from ..ingest.tagger import cross_tag_units
    stats = cross_tag_units(limit=limit)
    audit(request, user.username, "cross_tag", detail={
        "units": stats.get("units", 0), "auto": stats.get("auto_applied", 0)})
    return ok(stats, request)
