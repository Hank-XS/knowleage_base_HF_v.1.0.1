"""知识库工具实现（文档/代码/图谱/缓存/影响分析/预览/统计）。

所有工具返回 JSON 可序列化 dict，供 MCP / Agent / Flow 共用。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from ..config import settings
from ..knowledge import cache, retrieval
from ..knowledge.fingerprint import compute_fingerprint, normalize_question
from ..qa import analyzer
from ..qa.source_view import preview_source
from ..stores.graph import graph_store
from ..stores.vector import vector_store
from ..support import analyze_impact, generate_skeleton
from ..support_annotate import annotate_code


def _trim_evidence(items: list[dict], limit: int = 8) -> list[dict]:
    out = []
    for e in items[:limit]:
        out.append({
            "channel": e.get("channel"),
            "ref": e.get("ref"),
            "label": e.get("label"),
            "loc": e.get("loc", ""),
            "path": e.get("obj") or e.get("path") or e.get("label") or "",
            "score": e.get("rank_score", e.get("score")),
            "snippet": (e.get("text") or "")[:280],
            "graph_id": e.get("graph_id"),
        })
    return out


def tool_search_doc(query: str, top_k: int = 5) -> dict:
    """文档/错误码/报文语义检索。"""
    hits = retrieval.vector_evidence(query, ["kb_doc_chunk"], top_k or settings.retrieve_top_k)
    return {"tool": "search_doc", "query": query, "count": len(hits),
            "results": _trim_evidence(hits, top_k)}


def tool_search_code(query: str, top_k: int = 5) -> dict:
    """COBOL/代码 chunk 语义检索。"""
    hits = retrieval.vector_evidence(query, ["kb_code_chunk"], top_k or settings.retrieve_top_k)
    return {"tool": "search_code", "query": query, "count": len(hits),
            "results": _trim_evidence(hits, top_k)}


def tool_search_mapping(query: str, top_k: int = 5) -> dict:
    """字段映射检索。"""
    hits = retrieval.vector_evidence(query, ["kb_mapping_chunk"], top_k or settings.retrieve_top_k)
    return {"tool": "search_mapping", "query": query, "count": len(hits),
            "results": _trim_evidence(hits, top_k)}


def tool_search_graph(query: str, intent: str = "business_rule",
                      entities: list[str] | None = None) -> dict:
    """知识图谱检索：实体邻域 / 三层查全 / 影响面。"""
    ents = entities or analyzer.extract_entities(query, [])
    if query and query not in ents:
        ents = [query] + ents
    hits = retrieval.graph_evidence(ents[:6], intent or "business_rule")
    return {"tool": "search_graph", "query": query, "intent": intent,
            "entities": ents[:6], "count": len(hits),
            "results": _trim_evidence(hits, 10)}


def tool_query_cache(question: str, scene_code: str = "ATM") -> dict:
    """已验证答案三级分流（exact / similar / miss）。"""
    entities = analyzer.extract_entities(question, [])
    norm = normalize_question(question, scene_code, entities)
    fp = compute_fingerprint(norm)
    verdict = cache.lookup(fp, question, scene_code)
    payload = {
        "tool": "query_cache",
        "route": verdict.get("route"),
        "similarity": verdict.get("similarity", 0),
        "fingerprint": fp,
        "entities": entities,
    }
    if verdict.get("route") == "exact" and verdict.get("answer"):
        ans = verdict["answer"]
        payload["answer"] = ans.get("answer")
        payload["sources"] = ans.get("sources", [])[:8]
        payload["answer_id"] = ans.get("answer_id")
    elif verdict.get("route") == "similar" and verdict.get("answer"):
        payload["reference"] = cache.compress_reference(verdict["answer"])
    return payload


def tool_analyze_question(question: str) -> dict:
    """问题分析：意图 + 实体 + 改写。"""
    intent = analyzer.classify_intent(question)
    entities = analyzer.extract_entities(question, [])
    rewritten = analyzer.rewrite_query(question, entities, [])
    return {"tool": "analyze_question", "intent": intent,
            "entities": entities, "rewritten": rewritten}


def tool_retrieve_all(query: str, intent: str = "business_rule",
                      entities: list[str] | None = None, top_k: int = 5) -> dict:
    """多路融合检索（图谱+文档+代码+映射）并重排。"""
    ents = entities or analyzer.extract_entities(query, [])
    hits = retrieval.retrieve(query, intent or "business_rule", ents, top_k=top_k)
    return {"tool": "retrieve_all", "query": query, "intent": intent,
            "entities": ents, "count": len(hits),
            "results": _trim_evidence(hits, 12)}


def tool_impact_analyze(target: str, change_summary: str = "", depth: int = 3) -> dict:
    """迁移影响面分析。"""
    return {"tool": "impact_analyze", **analyze_impact(target, change_summary, depth)}


def tool_codegen_skeleton(interface_id: str, target: str = "spring_controller") -> dict:
    """代码骨架生成（仅骨架，不落地运行）。"""
    return {"tool": "codegen_skeleton", **generate_skeleton(interface_id, target)}


def tool_annotate_code(code: str, language: str = "cobol", hint: str = "") -> dict:
    """基于知识库为粘贴代码生成注释。"""
    result = annotate_code(code, language=language, hint=hint)
    # MCP 不宜返回超长正文
    annotated = result.get("annotated_code") or ""
    return {
        "tool": "annotate_code",
        **result,
        "annotated_code": annotated[:16_000],
        "truncated": len(annotated) > 16_000,
    }


def tool_preview_source(path: str = "", source_type: str = "doc",
                        ref: str = "", loc: str = "") -> dict:
    """依据文档/代码/图谱原文预览。"""
    doc = preview_source(path=path, source_type=source_type, ref=ref, loc=loc)
    # MCP 侧不宜返回超长正文，截断
    content = doc.get("content") or ""
    return {**doc, "content": content[:12_000],
            "truncated": len(content) > 12_000, "tool": "preview_source"}


def tool_kb_stats() -> dict:
    """知识库规模与存储状态。"""
    g = graph_store.stats()
    return {
        "tool": "kb_stats",
        "graph": g,
        "vector": {
            "kb_doc_chunk": vector_store.count("kb_doc_chunk"),
            "kb_code_chunk": vector_store.count("kb_code_chunk"),
            "kb_mapping_chunk": vector_store.count("kb_mapping_chunk"),
        },
    }


from .ingest_tools import INGEST_TOOL_HANDLERS, INGEST_TOOL_SPECS

TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "analyze_question": tool_analyze_question,
    "query_cache": tool_query_cache,
    "search_doc": tool_search_doc,
    "search_code": tool_search_code,
    "search_mapping": tool_search_mapping,
    "search_graph": tool_search_graph,
    "retrieve_all": tool_retrieve_all,
    "impact_analyze": tool_impact_analyze,
    "codegen_skeleton": tool_codegen_skeleton,
    "annotate_code": tool_annotate_code,
    "preview_source": tool_preview_source,
    "kb_stats": tool_kb_stats,
    **INGEST_TOOL_HANDLERS,
}

# OpenAI / MCP 共用的工具描述
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "analyze_question",
        "description": "分析用户问题：识别意图(intent)、实体、改写检索问句。回答前建议先调用。",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "用户原问题"}},
            "required": ["question"],
        },
    },
    {
        "name": "query_cache",
        "description": "查询已验证答案库（长时记忆）。返回 exact/similar/miss。"
                       "exact 时可直接采用答案；similar 可作参考；miss 需继续检索。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "scene_code": {"type": "string", "default": "ATM"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "search_doc",
        "description": "在业务文档/错误码表/报文说明中做语义检索，返回带路径的证据片段。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_code",
        "description": "在 COBOL/源码 chunk 中语义检索，适合程序行为、调用、实现细节问题。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_mapping",
        "description": "检索字段映射（新旧系统字段对应关系）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_graph",
        "description": "知识图谱检索：实体关系、业务/数据/执行三层查全、影响面。"
                       "intent 可选 business_rule / impact / entity。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "intent": {"type": "string", "default": "business_rule"},
                "entities": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
    },
    {
        "name": "retrieve_all",
        "description": "一次多路检索（图谱+文档+代码+映射）并重排，适合需要综合证据时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "intent": {"type": "string", "default": "business_rule"},
                "entities": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "impact_analyze",
        "description": "分析修改某程序/接口的影响面（波及对象、耦合度、风险等级）。",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "程序名或接口名，如 ATMWD402 / WIREXFR0"},
                "change_summary": {"type": "string", "default": ""},
                "depth": {"type": "integer", "default": 3},
            },
            "required": ["target"],
        },
    },
    {
        "name": "codegen_skeleton",
        "description": "根据接口生成代码骨架（仅参考，不落地主机运行）。",
        "parameters": {
            "type": "object",
            "properties": {
                "interface_id": {"type": "string"},
                "target": {"type": "string", "default": "spring_controller",
                           "enum": ["spring_controller", "python_script"]},
            },
            "required": ["interface_id"],
        },
    },
    {
        "name": "annotate_code",
        "description": "粘贴代码片段，基于知识库检索证据后生成带注释的代码（不改逻辑）。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "待注释的源代码文本"},
                "language": {"type": "string", "default": "cobol",
                             "description": "cobol / java / python 等"},
                "hint": {"type": "string", "default": "",
                         "description": "可选程序名或业务提示，辅助检索"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "preview_source",
        "description": "按路径或实体预览依据原文（文档/代码/图谱详情）。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "source_type": {"type": "string", "default": "doc"},
                "ref": {"type": "string"},
                "loc": {"type": "string"},
            },
        },
    },
    {
        "name": "kb_stats",
        "description": "查看知识库图谱节点/边数量与向量集合规模。",
        "parameters": {"type": "object", "properties": {}},
    },
    *INGEST_TOOL_SPECS,
]


def list_tools() -> list[dict]:
    return [{"name": s["name"], "description": s["description"],
             "input_schema": s["parameters"]} for s in TOOL_SPECS]


def invoke_tool(name: str, arguments: dict | None = None) -> dict:
    if name not in TOOL_HANDLERS:
        return {"error": f"未知工具：{name}", "available": list(TOOL_HANDLERS)}
    args = arguments or {}
    try:
        return TOOL_HANDLERS[name](**args)
    except TypeError as e:
        return {"error": f"参数错误：{e}", "tool": name, "arguments": args}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "tool": name}


def openai_tools() -> list[dict]:
    """OpenAI compatible tools 数组。"""
    return [{
        "type": "function",
        "function": {
            "name": s["name"],
            "description": s["description"],
            "parameters": s["parameters"],
        },
    } for s in TOOL_SPECS]


def dumps_result(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
