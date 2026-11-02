"""多路检索器：图谱 | 文档向量 | 代码 | 映射，融合去重后重排（设计 5.4 节）。"""
from __future__ import annotations

from ..config import settings
from ..stores.graph import graph_store
from ..stores.vector import vector_store

def graph_evidence(entities: list[str], intent: str) -> list[dict]:
    """图谱通道：实体邻域 / 三层查全 / 影响面。"""
    from .catalog import current_project_jobs
    current = current_project_jobs()
    out: list[dict] = []
    for ent in entities[:6]:
        nodes = [n for n in graph_store.find_by_name(ent) if not n['props'].get('project_job') or n['props']['project_job'] in current]
        if not nodes:
            continue
        for node in sorted(nodes, key=lambda n: (n['props'].get('kind') != 'module', n['label'] == 'Field'))[:4]:
            if intent in {"impact", "impact_analysis"}:
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
    """Shared hybrid recall. The public name is retained for tool/API compatibility."""
    from .hybrid import search
    return search(query, collections, top_k, vector_store, graph_store)


def retrieve(query: str, intent: str, entities: list[str], top_k: int | None = None) -> list[dict]:
    top_k = top_k or settings.retrieve_top_k
    evidence = vector_evidence(query, ["kb_doc_chunk", "kb_code_chunk", "kb_mapping_chunk"], max(12, top_k))
    evidence += graph_evidence(entities, intent)
    return fuse_and_rerank(query, evidence)


def fuse_and_rerank(query: str, evidences: list[dict]) -> list[dict]:
    from .hybrid import rank_evidence
    return rank_evidence(query, evidences)
