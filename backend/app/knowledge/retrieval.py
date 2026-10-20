"""多路检索器：图谱 | 文档向量 | 代码 | 映射，融合去重后重排（设计 5.4 节）。"""
from __future__ import annotations

import re
from typing import Any

from ..config import settings
from ..llm import get_embedder, get_reranker
from ..stores.graph import graph_store
from ..stores.vector import vector_store

_EVIDENCE_BUDGET = 12


def _kw(text: str) -> set[str]:
    return {w for w in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_\-]{3,}", text.lower())}


def graph_evidence(entities: list[str], intent: str) -> list[dict]:
    """图谱通道：实体邻域 / 三层查全 / 影响面。"""
    out: list[dict] = []
    for ent in entities[:6]:
        nodes = graph_store.find_by_name(ent)
        if not nodes:
            continue
        node = nodes[0]
        if intent == "impact":
            sub = graph_store.impact(node["id"], depth=3)
            out.append({"channel": "graph", "kind": "impact",
                        "ref": node["props"].get("name", node["id"]),
                        "label": f"影响面（波及 {sub['affected']} 个对象，耦合度 {sub['coupling_score']}）",
                        "text": "；".join(sub["paths"][:6]),
                        "graph_id": node["id"]})
            continue
        if node["label"] == "FunctionPoint":
            tl = graph_store.three_layer(node["props"].get("name", ent))
            summary = []
            for n in tl["nodes"]:
                if n["label"] in ("Interface", "MessageFormat", "Field", "CodeUnit", "ErrorCode", "BusinessRule"):
                    summary.append(f"{n['label']}:{n['props'].get('name', n['id'])}")
            out.append({"channel": "graph", "kind": "three_layer",
                        "ref": node["props"].get("name", ent),
                        "label": f"三层查全（{len(tl['nodes'])} 个关联对象）",
                        "text": "；".join(summary[:12]), "graph_id": node["id"]})
            continue
        ns, es = graph_store.neighbors(node["id"], max_hops=1)
        rel_summary = [f"{e['rel']}->{graph_store.node(e['dst'])['props'].get('name', e['dst']) if graph_store.node(e['dst']) else e['dst']}"
                       for e in es[:8]]
        out.append({"channel": "graph", "kind": "entity",
                    "ref": node["props"].get("name", ent),
                    "label": f"图谱实体（{node['label']}）",
                    "text": "；".join(rel_summary) or node["props"].get("desc", ""),
                    "graph_id": node["id"],
                    "props": {k: v for k, v in node["props"].items() if k in ("meaning", "action", "level", "rule", "desc", "caliber")}})
    return out


def vector_evidence(query: str, collections: list[str], top_k: int) -> list[dict]:
    emb = get_embedder()
    qv = emb.embed([query])[0]
    out: list[dict] = []
    # CPS/关键路径类问题需要更长正文，避免架构文档前半段元数据把路径章节截掉
    text_limit = 1400 if re.search(r"CPS|关键路径|跨境|SWIFT|PYMAIN|汇出", query, re.I) else 700
    for col in collections:
        for hit in vector_store.search(col, qv, top_k=top_k):
            meta = hit["meta"]
            score = float(hit["score"])
            # 查询命中 CPS 时，提升 CPS universe / 关键路径专用 chunk
            if re.search(r"CPS|跨境|汇出|SWIFT", query, re.I):
                if (meta.get("universe") or "").upper() == "CPS":
                    score += 0.08
                if "critical_path" in hit["id"] or "关键路径" in (meta.get("title") or ""):
                    score += 0.12
            out.append({
                "channel": "doc" if col == "kb_doc_chunk" else ("code" if col == "kb_code_chunk" else "mapping"),
                "kind": "chunk",
                "score": round(min(score, 1.0), 4),
                "ref": meta.get("title") or meta.get("code_unit") or meta.get("business_key") or hit["id"],
                "label": f"{meta.get('source_path', col)}",
                "text": meta.get("text", "")[:text_limit],
                "obj": meta.get("source_path"),
                "loc": meta.get("loc", ""),
            })
    return out


def retrieve(query: str, intent: str, entities: list[str], top_k: int | None = None) -> list[dict]:
    top_k = top_k or settings.retrieve_top_k
    evidences: list[dict] = []
    # 跨境/CPS 问题强制带上关键实体，避免实体抽取落到 ATM
    ents = list(entities or [])
    if re.search(r"CPS|跨境|汇出|SWIFT|关键路径", query, re.I):
        for force in ("CPS", "PYMAIN", "PYROUTE", "PYPOST", "CGW"):
            if force not in ents:
                ents.append(force)
    evidences += graph_evidence(ents, intent)
    cols = ["kb_doc_chunk", "kb_code_chunk", "kb_mapping_chunk"]
    evidences += vector_evidence(query, cols, top_k)

    # 去重（channel+ref）
    seen, uniq = set(), []
    for e in evidences:
        key = (e["channel"], e["ref"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return fuse_and_rerank(query, uniq)


def fuse_and_rerank(query: str, evidences: list[dict]) -> list[dict]:
    """重排：TEI 可用时用模型分，否则启发式（关键词重合 + 向量分 + 图谱加成）。"""
    rr = get_reranker()
    if rr and evidences:
        try:
            scores = rr.rerank(query, [e.get("text", "") for e in evidences])
            for e, s in zip(evidences, scores):
                e["rank_score"] = round(float(s), 4)
            evidences.sort(key=lambda x: -x["rank_score"])
            return evidences[:_EVIDENCE_BUDGET]
        except Exception:
            pass
    qkw = _kw(query)
    cps_q = bool(re.search(r"CPS|跨境|汇出|SWIFT|关键路径", query, re.I))
    for e in evidences:
        overlap = len(qkw & _kw(e.get("text", "") + e.get("ref", "")))
        base = e.get("score", 0.5)
        bonus = 0.15 if e["channel"] == "graph" else 0.0
        blob = (e.get("text", "") + e.get("label", "") + e.get("ref", ""))
        if cps_q and re.search(r"CPS\.IN\.Q|PYMAIN|关键路径|ARCH-PAY|跨境汇出", blob):
            bonus += 0.18
        if cps_q and re.search(r"ATMWD|atm_withdraw|CardDemo", blob, re.I):
            bonus -= 0.12
        e["rank_score"] = round(min(1.0, max(0.0, 0.5 * base + 0.3 * min(overlap, 5) / 5 + bonus + 0.05)), 4)
    evidences.sort(key=lambda x: -x["rank_score"])
    return evidences[:_EVIDENCE_BUDGET]
