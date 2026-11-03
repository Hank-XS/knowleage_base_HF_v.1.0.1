"""长时记忆：已验证答案库的三级分流与失效联动（设计 5.3 / 4.6 节）。"""
from __future__ import annotations

import json
import math
import re

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, VerifiedAnswer, IngestJob
from ..llm import get_embedder
from .fingerprint import route_by_similarity


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def lookup(fingerprint: str, question: str, scene_code: str) -> dict:
    """返回 {route, answer?, similarity?}。route ∈ exact / similar / miss。"""
    with SessionLocal() as db:
        rows = db.execute(
            select(VerifiedAnswer).where(VerifiedAnswer.scene_code == scene_code)
        ).scalars().all()
        from .catalog import current_project_jobs
        current = current_project_jobs()
        reusable = current - {job.id for job in db.scalars(select(IngestJob).where(IngestJob.id.in_(current)))
                              if job.options_json.get('cleaned_chunks') or job.options_json.get('cleaned_graph')}
        def current_sources(row):
            from .scope import active_scope
            scope = active_scope()
            if scope and any(not scope.allows(s.get('path') or s.get('obj') or '') for s in (row.sources_json or [])):
                return False
            from ..db import KbDocument
            managed = {s.get('path') or s.get('obj') for s in (row.sources_json or [])
                       if str(s.get('path') or s.get('obj') or '').startswith('kb-managed/documents/')}
            if managed:
                active_paths = set(db.scalars(select(KbDocument.source_path).where(KbDocument.is_current == 1,
                    KbDocument.vectorized == 1)).all())
                if not managed <= active_paths:
                    return False
            jobs = {match for source in (row.sources_json or []) for value in
                    (source.get('path', ''), source.get('obj', ''), source.get('ref', ''))
                    for match in re.findall(r'(?:projects/|project/)([0-9a-f]{32})(?:/|$)', value or '')}
            return jobs <= reusable
        rows = [row for row in rows if row.status == 'verified' and current_sources(row)]
        if not rows:
            return {'route': 'miss', 'similarity': 0.0}
        # A newly uploaded same-named file must not reuse an earlier unscoped answer.
        from .hybrid import code_scope
        from ..stores.graph import graph_store
        _, matched = code_scope(question, graph_store, current, [])
        if len({(d.library_key, d.project) for d in matched}) > 1:
            return {'route': 'miss', 'similarity': 0.0}
        for row in rows:
            if row.fingerprint == fingerprint:
                return {"route": "exact", "answer": _payload(row), "similarity": 1.0}
        emb = get_embedder()
        qv = emb.embed([question])[0]
        best, best_sim = None, 0.0
        for row in rows:
            if row.status != "verified":
                continue
            encoded = json.loads(row.question_emb or "[]")
            if isinstance(encoded, dict):
                if encoded.get('embedding_space') != emb.name:
                    continue
                rv = encoded.get('vector', [])
            else:
                # Legacy unversioned vectors are never compared with new semantic spaces.
                if not emb.name.startswith('hash:'):
                    continue
                rv = encoded
            sim = _cos(qv, rv)
            if sim > best_sim:
                best, best_sim = row, sim
        route = route_by_similarity(best_sim)
        if route in {"exact", "similar"} and best is not None:
            return {"route": "similar", "answer": _payload(best), "similarity": round(best_sim, 4)}
        return {"route": "miss", "similarity": round(best_sim, 4)}


def _payload(row: VerifiedAnswer) -> dict:
    return {
        "answer_id": row.answer_id,
        "fingerprint": row.fingerprint,
        "answer": row.answer_json,
        "sources": row.sources_json or [],
        "kb_version": row.kb_version,
        "verified_by": row.verified_by,
    }


def save_verified(*, fingerprint: str, question_norm: str, scene_code: str,
                  answer: dict, sources: list, hit_type: str, verified_by: str,
                  kb_version: str, question: str) -> str:
    emb = get_embedder()
    qv = emb.embed([question])[0]
    with SessionLocal() as db:
        row = db.execute(
            select(VerifiedAnswer).where(VerifiedAnswer.fingerprint == fingerprint,
                                         VerifiedAnswer.scene_code == scene_code)
        ).scalar_one_or_none()
        if row is None:
            row = VerifiedAnswer(fingerprint=fingerprint, scene_code=scene_code)
            db.add(row)
        row.question_norm = question_norm
        row.answer_json = answer
        row.sources_json = sources
        row.hit_type = hit_type
        row.status = "verified"
        row.verified_by = verified_by
        row.kb_version = kb_version
        row.question_emb = json.dumps(dict(embedding_space=emb.name, vector=qv))
        db.commit()
        return row.answer_id


def compress_reference(payload: dict, max_chars: int = 600) -> str:
    """相似命中时压缩旧答案为参考上下文（结论保留、依据截断）。"""
    ans = payload.get("answer", {})
    parts = [f"历史结论：{ans.get('what', '')}",
             f"历史处理：{ans.get('how', '')}"]
    text = "\n".join(parts)
    return text[:max_chars]


def invalidate_by_objects(changed_objs: list[str]) -> int:
    """知识版本变更联动：溯源对象与变更对象有交集的已验证答案置为 stale。"""
    changed = {str(o) for o in changed_objs}
    n = 0
    with SessionLocal() as db:
        rows = db.execute(select(VerifiedAnswer)).scalars().all()
        for row in rows:
            if row.status != "verified":
                continue
            refs = {s.get("obj") or s.get("ref") for s in (row.sources_json or [])}
            if refs & changed:
                row.status = "stale"
                n += 1
        db.commit()
    return n
