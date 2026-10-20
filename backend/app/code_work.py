"""代码树工作结果持久化（注释 / 式样书 → 本地库）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

import datetime as dt

from .db import CodeWorkResult, SessionLocal


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _key(path: str, symbol: str = "") -> tuple[str, str]:
    return (path or "").replace("\\", "/").strip(), (symbol or "").strip()


def _row_dict(row: CodeWorkResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "path": row.path,
        "symbol": row.symbol,
        "language": row.language,
        "hint": row.hint,
        "has_annotate": bool((row.annotated_code or "").strip()),
        "has_spec": bool((row.spec_markdown or "").strip()),
        "annotated_code": row.annotated_code or "",
        "annotate": row.annotate_json or {},
        "prompt_type": row.prompt_type or "",
        "spec_markdown": row.spec_markdown or "",
        "spec": row.spec_json or {},
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def get_work(path: str, symbol: str = "") -> dict[str, Any] | None:
    p, s = _key(path, symbol)
    if not p:
        return None
    with SessionLocal() as db:
        row = db.execute(
            select(CodeWorkResult).where(
                CodeWorkResult.path == p, CodeWorkResult.symbol == s)
        ).scalar_one_or_none()
        return _row_dict(row) if row else None


def save_annotate(
    *,
    path: str,
    symbol: str = "",
    language: str = "cobol",
    hint: str = "",
    source_code: str = "",
    annotate_result: dict[str, Any],
    actor: str = "",
) -> dict[str, Any]:
    p, s = _key(path, symbol)
    if not p:
        p = "__paste__"
    with SessionLocal() as db:
        row = db.execute(
            select(CodeWorkResult).where(
                CodeWorkResult.path == p, CodeWorkResult.symbol == s)
        ).scalar_one_or_none()
        if row is None:
            row = CodeWorkResult(path=p, symbol=s)
            db.add(row)
        row.language = language or row.language
        row.hint = hint or ""
        row.source_code = (source_code or "")[:50_000]
        row.annotated_code = annotate_result.get("annotated_code") or ""
        # 存精简 JSON，避免过大
        row.annotate_json = {
            "language": annotate_result.get("language"),
            "notes": annotate_result.get("notes") or [],
            "uncovered": annotate_result.get("uncovered"),
            "disclaimer": annotate_result.get("disclaimer"),
            "sources": (annotate_result.get("sources") or [])[:20],
            "entities": (annotate_result.get("entities") or [])[:20],
            "query": annotate_result.get("query"),
        }
        # 重新注释后清空旧式样书（需基于新注释再生成）
        row.spec_markdown = ""
        row.spec_json = {}
        row.prompt_type = ""
        row.updated_by = actor or row.updated_by
        row.updated_at = _now()
        db.commit()
        db.refresh(row)
        return _row_dict(row)


def save_spec(
    *,
    path: str,
    symbol: str = "",
    language: str = "cobol",
    hint: str = "",
    prompt_type: str = "",
    spec_result: dict[str, Any],
    actor: str = "",
) -> dict[str, Any]:
    p, s = _key(path, symbol)
    if not p:
        p = "__paste__"
    with SessionLocal() as db:
        row = db.execute(
            select(CodeWorkResult).where(
                CodeWorkResult.path == p, CodeWorkResult.symbol == s)
        ).scalar_one_or_none()
        if row is None:
            row = CodeWorkResult(path=p, symbol=s)
            db.add(row)
        row.language = language or row.language
        row.hint = hint or row.hint
        if spec_result.get("annotated_code") and not row.annotated_code:
            row.annotated_code = spec_result["annotated_code"]
        row.prompt_type = prompt_type or spec_result.get("prompt_type") or ""
        row.spec_markdown = spec_result.get("markdown") or ""
        row.spec_json = {
            "title": spec_result.get("title"),
            "prompt_type": spec_result.get("prompt_type"),
            "notes": spec_result.get("notes") or [],
            "uncovered": spec_result.get("uncovered"),
            "disclaimer": spec_result.get("disclaimer"),
            "sources": (spec_result.get("sources") or [])[:20],
            "entities": (spec_result.get("entities") or [])[:20],
        }
        row.updated_by = actor or row.updated_by
        row.updated_at = _now()
        db.commit()
        db.refresh(row)
        return _row_dict(row)
