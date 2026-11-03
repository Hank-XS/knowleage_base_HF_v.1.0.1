"""多路检索器：图谱 | 文档向量 | 代码 | 映射，融合去重后重排（设计 5.4 节）。"""
from __future__ import annotations

from ..config import settings
from ..stores.graph import graph_store
from ..stores.vector import vector_store

def graph_evidence(entities: list[str], intent: str) -> list[dict]:
    """图谱通道：实体邻域 / 三层查全 / 影响面。"""
    from .catalog import current_project_jobs
    current = current_project_jobs()
    from .scope import active_scope
    scope = active_scope()
    from .relations import relation_graph
    graph = relation_graph(graph_store)
    out: list[dict] = []
    for ent in entities[:6]:
        nodes = [n for n in graph.find_by_name(ent) if not n['props'].get('project_job') or n['props']['project_job'] in current]
        if scope:
            nodes = [n for n in nodes if scope.allows(n['props'].get('source_path', ''))]
        if scope and scope.paths is not None:
            nodes = [n for n in nodes if n['props'].get('source_path') in scope.paths]
        if not nodes:
            continue
        for node in sorted(nodes, key=lambda n: (n['props'].get('kind') != 'module', n['label'] == 'Field'))[:4]:
            if intent in {"impact", "impact_analysis"}:
                sub = graph.impact(node["id"], depth=3)
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
            ns, es = graph.neighbors(node["id"], max_hops=1)
            rel_summary = []
            for edge in es[:12]:
                src, dst = graph.node(edge['src']), graph.node(edge['dst'])
                rel_summary.append(f"{(src or {}).get('props', {}).get('name', edge['src'])} --{edge['rel']}--> {(dst or {}).get('props', {}).get('name', edge['dst'])}")
            out.append({"channel": "graph", "kind": "entity",
                        "ref": node["props"].get("name", ent),
                        "label": f"图谱实体（{node['label']}）",
                        "text": "静态结构关系（不证明运行时必然执行）：" + ("；".join(rel_summary) or node["props"].get("desc", "")),
                        "graph_id": node["id"],
                        "source_path": node['props'].get('source_path', ''),
                        "project": node['props'].get('project', ''),
                        "library": node['props'].get('library', ''),
                        "version": node['props'].get('version', ''),
                        "props": {k: v for k, v in node["props"].items() if k in ("meaning", "action", "level", "rule", "desc", "caliber")}})
    return out


def vector_evidence(query: str, collections: list[str], top_k: int, *, rerank: bool = True) -> list[dict]:
    """Shared hybrid recall. The public name is retained for tool/API compatibility."""
    from .hybrid import search
    return search(query, collections, top_k, vector_store, graph_store, rerank=rerank)


def retrieve(query: str, intent: str, entities: list[str], top_k: int | None = None) -> list[dict]:
    top_k = top_k or settings.retrieve_top_k
    # Gather a cheap candidate pool. Rerank once after graph and source context join it.
    evidence = vector_evidence(query, ["kb_doc_chunk", "kb_code_chunk", "kb_mapping_chunk"],
        max(30, top_k, settings.kb_rerank_candidates), rerank=False)
    if any(e.get('kind') == 'ambiguous_scope' for e in evidence):
        return evidence  # Do not mix clarification candidates with facts from competing objects.
    evidence += graph_evidence(entities, intent)
    from .context import context_evidence
    context = context_evidence(query, evidence[:max(12, top_k)], graph_store)
    from .scope import active_scope
    scope = active_scope()
    if scope:
        context = [e for e in context if scope.allows(e.get('path') or e.get('obj') or '')]
    for item in context:
        if scope:
            scope.learn(item)
    ranked = fuse_and_rerank(query, [*evidence, *context])
    # Caller/definition passages must not be crowded out by several graph summaries.
    chosen = ranked[:top_k]
    for item in context:
        if not any(e.get('path') == item['path'] and e.get('loc') == item['loc'] for e in chosen):
            chosen.append(item)
    from .passage import bounded, expand_parents, pack
    # Deduplicate and merge before numbering so expanded ranges retain their full evidence budget.
    from .evidence import EvidenceRegistry
    registry = EvidenceRegistry()
    for item in expand_parents(chosen):
        registry.add(bounded(item))
    return pack(registry.items[:max(top_k, 10)], settings.context_budget_tokens)


def fuse_and_rerank(query: str, evidences: list[dict]) -> list[dict]:
    from .hybrid import rank_evidence
    return rank_evidence(query, evidences)
