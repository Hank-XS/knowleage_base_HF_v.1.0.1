"""工具接口层 + 单一 Flow 编排器（设计 5.1 / 6 章）。

SingleFlowOrchestrator 按固定序列调用注册工具：
  query_cache → (未直出) search_graph / search_doc / search_code → (LLM 合成)
演进到 Agent 动态编排时，仅替换编排器，工具与数据层零改动。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..config import settings
from ..db import QaMessage, SessionLocal
from ..knowledge import cache, retrieval
from ..knowledge.fingerprint import compute_fingerprint, normalize_question
from ..llm import get_llm
from ..tools.handlers import TOOL_SPECS, invoke_tool as tools_invoke
from . import analyzer, prompts


# ---------------------------------------------------------------- 工具注册中心（与 MCP / Agent 共用 handlers）
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Any]
    idempotent: bool = True
    timeout_ms: int = 3000


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def specs(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "input_schema": t.input_schema,
                 "idempotent": t.idempotent, "timeout_ms": t.timeout_ms}
                for t in self._tools.values()]

    def invoke(self, name: str, payload: dict) -> Any:
        if name not in self._tools:
            raise KeyError(f"未注册工具：{name}")
        return self._tools[name].handler(payload or {})


registry = ToolRegistry()

# 兼容旧 Flow：query_cache 仍按 fingerprint 直查；其余委托统一 handlers
registry.register(ToolSpec(
    "search_graph", "在知识图谱中检索实体、关系与路径（业务/数据/执行三层一次查全）",
    {"type": "object", "properties": {"query": {"type": "string"},
                                      "params": {"type": "object"},
                                      "top_k": {"type": "integer", "default": 10}},
     "required": ["query"]},
    lambda p: retrieval.graph_evidence(
        p.get("params", {}).get("entities", []) or [p.get("query", "")],
        p.get("params", {}).get("intent", "business_rule"))))

registry.register(ToolSpec(
    "search_doc", "文档语义检索（业务文档/错误码/报文 chunk）",
    {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
     "required": ["query"]},
    lambda p: tools_invoke("search_doc", p).get("results", [])))

registry.register(ToolSpec(
    "search_code", "代码检索（COBOL 节级 chunk＋图谱调用链）",
    {"type": "object", "properties": {"entity": {"type": "string"}, "kinds": {"type": "array"}},
     "required": ["entity"]},
    lambda p: tools_invoke("search_code", {
        "query": p.get("entity") or p.get("query", ""), "top_k": p.get("top_k")}).get("results", [])))

registry.register(ToolSpec(
    "query_cache", "缓存三级分流判定（exact / similar / miss）",
    {"type": "object", "properties": {"fingerprint": {"type": "string"}, "query": {"type": "string"}},
     "required": ["fingerprint"]},
    lambda p: cache.lookup(p.get("fingerprint", ""), p.get("query", ""), "ATM")))

registry.register(ToolSpec(
    "save_answer", "已验证答案入库（长时记忆沉淀）",
    {"type": "object", "properties": {"fingerprint": {"type": "string"}, "answer": {"type": "object"}},
     "required": ["fingerprint", "answer"]},
    lambda p: p, idempotent=False))

# 同步注册 MCP 扩展工具，便于 /admin/tools 发现
for _spec in TOOL_SPECS:
    if _spec["name"] in registry._tools:
        continue
    registry.register(ToolSpec(
        _spec["name"], _spec["description"], _spec["parameters"],
        lambda p, n=_spec["name"]: tools_invoke(n, p)))


# ---------------------------------------------------------------- 会话上下文
@dataclass
class SessionContext:
    session_id: str
    scene_code: str = "ATM"
    user: str = ""
    question: str = ""
    history: list[dict] = field(default_factory=list)


@dataclass
class AnswerContext:
    answer_id: str = ""
    hit_type: str = "miss"
    similarity: float = 0.0
    answer: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    reasoning_trace: list = field(default_factory=list)
    review_status: str = "pending_review"
    entities: list = field(default_factory=list)
    intent: str = ""
    elapsed_ms: int = 0


# ---------------------------------------------------------------- 单一 Flow
class SingleFlowOrchestrator:
    """固定序列编排：问题分析 → 指纹/分流 → 多路检索 → 重排 → LLM 合成 → 溯源输出。"""

    def run(self, ctx: SessionContext) -> AnswerContext:
        t0 = time.time()
        ac = AnswerContext()
        trace = ac.reasoning_trace

        # 1) 问题分析
        intent = analyzer.classify_intent(ctx.question)
        entities = analyzer.extract_entities(ctx.question, ctx.history)
        rewritten = analyzer.rewrite_query(ctx.question, entities, ctx.history)
        ac.intent, ac.entities = intent, entities
        trace.append({"step": 1, "tool": "analyzer",
                      "result": f"intent={intent}, entities={entities}"})

        # 2) 指纹 + 三级分流
        norm = normalize_question(ctx.question, ctx.scene_code, entities)
        fp = compute_fingerprint(norm)
        verdict = registry.invoke("query_cache", {"fingerprint": fp, "query": rewritten})
        trace.append({"step": 2, "tool": "query_cache",
                      "result": f"{verdict['route']}({verdict.get('similarity', 0)})"})
        ac.hit_type, ac.similarity = verdict["route"], verdict.get("similarity", 0.0)

        if verdict["route"] == "exact":
            payload = verdict["answer"]
            ac.answer = payload["answer"]
            ac.sources = payload["sources"]
            ac.review_status = "verified"
            ac.answer_id = payload["answer_id"]
            ac.elapsed_ms = int((time.time() - t0) * 1000)
            self._persist(ctx, ac, fingerprint=fp, norm=norm)
            return ac

        reference = ""
        if verdict["route"] == "similar":
            reference = cache.compress_reference(verdict["answer"])

        # 3) 多路检索（并行通道，串行调用演示）
        evidences = retrieval.retrieve(rewritten, intent, entities)
        trace.append({"step": 3, "tool": "search_graph+doc+code",
                      "result": f"{len(evidences)} 条证据（含重排）"})

        # 4) LLM 整体分析 + 答案生成
        llm = get_llm()
        is_mock = type(llm).__name__ != "ApiLLM"
        ev_lines = [f"{e.get('ref', '')}｜{e.get('label', '')}｜{(e.get('text', '') or '')[:200]}"
                    for e in evidences]
        history_lines = [f"Q: {h.get('question', '')} A: {str(h.get('answer', {}).get('what', ''))[:80]}"
                         for h in ctx.history]
        messages = prompts.build_synthesis_messages(
            ctx.scene_code, ctx.question, ev_lines, reference, history_lines,
            mock=is_mock, evidence=evidences)
        raw = llm.chat(messages, temperature=0.2, json_mode=not is_mock)
        answer = self._parse_answer(raw)
        trace.append({"step": 4, "tool": "llm_synthesis",
                      "result": f"{llm.name} 生成答案（confidence={answer.get('confidence')}）"})

        # 5) 溯源标注
        ac.answer = answer
        ac.sources = self._sources(evidences)
        ac.review_status = "pending_review" if ctx.question else "pending_review"
        ac.elapsed_ms = int((time.time() - t0) * 1000)
        self._persist(ctx, ac, fingerprint=fp, norm=norm)
        return ac

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _parse_answer(raw: str) -> dict:
        try:
            start, end = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[start:end + 1])
        except Exception:
            data = {"what": raw.strip()[:500], "why": "", "how": "",
                    "caveats": [], "confidence": 0.4, "uncovered": False}
        return {k: data.get(k, "" if k != "caveats" else []) for k in
                ("what", "why", "how", "caveats", "confidence", "uncovered")}

    @staticmethod
    def _sources(evidences: list[dict]) -> list[dict]:
        out = []
        for i, e in enumerate(evidences, start=1):
            # path：文档/代码相对路径；图谱用 graph_id 便于预览
            path = e.get("obj") or e.get("path") or ""
            if e.get("channel") == "graph" and e.get("graph_id"):
                path = path or e["graph_id"]
            # label 常为 source_path，补齐 path
            label = e.get("label", "")
            if not path and label and ("/" in label or "\\" in label):
                path = label
            out.append({
                "no": i, "type": e.get("channel", "doc"),
                "ref": e.get("ref", ""), "label": label,
                "loc": e.get("loc", ""), "obj": e.get("obj") or e.get("graph_id") or "",
                "path": path,
                "snippet": (e.get("text", "") or "")[:160],
                "score": e.get("rank_score", e.get("score", 0)),
            })
        return out

    def _persist(self, ctx: SessionContext, ac: AnswerContext, *, fingerprint: str, norm: str) -> None:
        with SessionLocal() as db:
            msg = QaMessage(
                session_id=ctx.session_id, question=ctx.question,
                answer_id="", hit_type=ac.hit_type,
                payload_json={
                    "fingerprint": fingerprint, "question_norm": norm,
                    "answer": ac.answer, "sources": ac.sources,
                    "reasoning_trace": ac.reasoning_trace,
                    "review_status": ac.review_status,
                    "entities": ac.entities, "intent": ac.intent,
                    "similarity": ac.similarity,
                })
            db.add(msg)
            db.commit()
            ac.answer_id = msg.id


flow = SingleFlowOrchestrator()
