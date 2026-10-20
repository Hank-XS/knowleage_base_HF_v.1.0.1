"""Agent 编排：由 LLM 自动选择并调度 MCP/工具层能力。

- 配置了真实 LLM Key：OpenAI 兼容 tool calling 多轮调度；
- Mock 模式：启发式选工具后走模板综合（保证无 Key 可演示）。
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..db import QaMessage, SessionLocal
from ..knowledge.fingerprint import compute_fingerprint, normalize_question
from ..llm import get_llm
from ..llm.base import ApiLLM, MockLLM
from ..qa.flow import AnswerContext, SessionContext
from ..qa.prompts import build_synthesis_messages
from .handlers import dumps_result, invoke_tool, openai_tools, tool_retrieve_all

MAX_ROUNDS = 6

SYSTEM_PROMPT = """你是某行核心系统迁移知识库助手。你必须通过工具检索证据后再回答，禁止编造。

可用策略：
1) 先 analyze_question，再 query_cache；
2) exact 命中则可直接整理答案；
3) 否则按需调用 search_graph / search_doc / search_code / search_mapping 或 retrieve_all；
4) 影响面问题用 impact_analyze；需要看原文用 preview_source。

最终必须输出严格 JSON：
{"what":"...","why":"...","how":"...","caveats":[],"confidence":0.0~1.0,"uncovered":false,"used_tools":["..."]}
why/how 中引用证据时用［1］［2］编号，对应你检索到的结果顺序。
"""


class AgentOrchestrator:
    """LLM 自动调度工具的问答编排器。"""

    def run(self, ctx: SessionContext) -> AnswerContext:
        t0 = time.time()
        llm = get_llm()
        if isinstance(llm, ApiLLM):
            return self._run_api(ctx, llm, t0)
        return self._run_heuristic(ctx, t0)

    # ---------------------------------------------------------------- API tool-calling
    def _run_api(self, ctx: SessionContext, llm: ApiLLM, t0: float) -> AnswerContext:
        ac = AnswerContext()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._user_payload(ctx)},
        ]
        used: list[str] = []
        evidences: list[dict] = []

        for round_i in range(MAX_ROUNDS):
            resp = llm.chat_tools(messages, tools=openai_tools(), temperature=0.1)
            tool_calls = resp.get("tool_calls") or []
            content = resp.get("content") or ""

            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except json.JSONDecodeError:
                        args = {}
                    result = invoke_tool(name, args)
                    used.append(name)
                    ac.reasoning_trace.append({
                        "step": len(ac.reasoning_trace) + 1,
                        "tool": name,
                        "result": _trace_summary(result),
                    })
                    # 收集证据供溯源
                    for r in result.get("results") or []:
                        evidences.append({
                            "channel": r.get("channel") or _channel_of(name),
                            "ref": r.get("ref"), "label": r.get("label"),
                            "loc": r.get("loc", ""), "obj": r.get("path"),
                            "path": r.get("path"), "text": r.get("snippet"),
                            "score": r.get("score"), "graph_id": r.get("graph_id"),
                        })
                    if result.get("route") == "exact" and result.get("answer"):
                        ac.hit_type = "exact"
                        ac.similarity = float(result.get("similarity") or 1.0)
                        ac.answer = result["answer"]
                        ac.sources = result.get("sources") or []
                        ac.review_status = "verified"
                        ac.answer_id = result.get("answer_id") or ""
                        ac.elapsed_ms = int((time.time() - t0) * 1000)
                        ac.reasoning_trace.append({
                            "step": len(ac.reasoning_trace) + 1,
                            "tool": "agent",
                            "result": f"exact 命中，跳过后续工具（used={used}）",
                        })
                        self._persist(ctx, ac)
                        return ac
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or name,
                        "content": dumps_result(result)[:8000],
                    })
                continue

            # 无 tool_calls → 最终答案
            answer = _parse_answer(content)
            ac.answer = answer
            ac.hit_type = ac.hit_type or "miss"
            ac.entities = answer.get("entities") or []
            ac.intent = "agent"
            ac.sources = _sources_from_evidences(evidences)
            ac.review_status = "pending_review"
            ac.reasoning_trace.append({
                "step": len(ac.reasoning_trace) + 1,
                "tool": "llm_synthesis",
                "result": f"agent 完成，调用工具 {used}",
            })
            ac.elapsed_ms = int((time.time() - t0) * 1000)
            self._persist(ctx, ac)
            return ac

        # 轮次耗尽：用已收集证据模板收尾
        return self._finalize_with_evidence(ctx, evidences, used, t0, hit_type="miss")

    # ---------------------------------------------------------------- Mock / 无 Key
    def _run_heuristic(self, ctx: SessionContext, t0: float) -> AnswerContext:
        """无真实 LLM 时的启发式工具调度。"""
        ac = AnswerContext()
        q = ctx.question
        analysis = invoke_tool("analyze_question", {"question": q})
        ac.intent = analysis.get("intent", "")
        ac.entities = analysis.get("entities") or []
        ac.reasoning_trace.append({"step": 1, "tool": "analyze_question",
                                   "result": _trace_summary(analysis)})

        cache_res = invoke_tool("query_cache", {"question": q, "scene_code": ctx.scene_code})
        ac.reasoning_trace.append({"step": 2, "tool": "query_cache",
                                   "result": _trace_summary(cache_res)})
        ac.hit_type = cache_res.get("route", "miss")
        ac.similarity = float(cache_res.get("similarity") or 0)

        if cache_res.get("route") == "exact" and cache_res.get("answer"):
            ac.answer = cache_res["answer"]
            ac.sources = cache_res.get("sources") or []
            ac.review_status = "verified"
            ac.answer_id = cache_res.get("answer_id") or ""
            ac.elapsed_ms = int((time.time() - t0) * 1000)
            self._persist(ctx, ac)
            return ac

        used = ["analyze_question", "query_cache"]
        ql = q.lower()
        evidences: list[dict] = []

        # 按问题特征调度工具
        if any(k in q for k in ("影响", "波及", "修改")) or "impact" in ql:
            target = (ac.entities[0] if ac.entities else q.split()[0] if q.split() else q)
            imp = invoke_tool("impact_analyze", {"target": target, "change_summary": q})
            used.append("impact_analyze")
            ac.reasoning_trace.append({"step": 3, "tool": "impact_analyze",
                                       "result": _trace_summary(imp)})
            evidences.append({
                "channel": "graph", "ref": target,
                "label": f"影响面 risk={imp.get('risk_level')}",
                "text": json.dumps(imp.get("affected") or imp, ensure_ascii=False)[:400],
                "path": target,
            })

        need_code = any(k in ql for k in ("program", "cobol", "cbl", "call")) or \
            any(k in q for k in ("程序", "代码", "调用", "WIREXFR", "PYMAIN", "PYROUTE", "COACT"))
        need_graph = any(k in q for k in ("关系", "依赖", "图谱", "FR-", "需求", "宇宙")) or bool(ac.entities)
        need_doc = True

        if need_graph:
            g = invoke_tool("search_graph", {
                "query": analysis.get("rewritten") or q,
                "intent": "impact" if "影响" in q else ac.intent or "business_rule",
                "entities": ac.entities,
            })
            used.append("search_graph")
            ac.reasoning_trace.append({"step": len(ac.reasoning_trace) + 1, "tool": "search_graph",
                                       "result": _trace_summary(g)})
            evidences.extend(_to_ev(g.get("results") or [], "graph"))

        if need_doc:
            d = invoke_tool("search_doc", {"query": analysis.get("rewritten") or q, "top_k": 5})
            used.append("search_doc")
            ac.reasoning_trace.append({"step": len(ac.reasoning_trace) + 1, "tool": "search_doc",
                                       "result": _trace_summary(d)})
            evidences.extend(_to_ev(d.get("results") or [], "doc"))

        if need_code:
            c = invoke_tool("search_code", {"query": analysis.get("rewritten") or q, "top_k": 5})
            used.append("search_code")
            ac.reasoning_trace.append({"step": len(ac.reasoning_trace) + 1, "tool": "search_code",
                                       "result": _trace_summary(c)})
            evidences.extend(_to_ev(c.get("results") or [], "code"))

        if not evidences:
            all_hits = tool_retrieve_all(analysis.get("rewritten") or q,
                                         ac.intent or "business_rule", ac.entities)
            used.append("retrieve_all")
            ac.reasoning_trace.append({"step": len(ac.reasoning_trace) + 1, "tool": "retrieve_all",
                                       "result": _trace_summary(all_hits)})
            evidences.extend(_to_ev(all_hits.get("results") or [], "doc"))

        return self._finalize_with_evidence(
            ctx, evidences, used, t0,
            hit_type=ac.hit_type or "miss",
            similarity=ac.similarity,
            reference=cache_res.get("reference", ""),
            entities=ac.entities,
            intent=ac.intent,
        )

    def _finalize_with_evidence(
        self, ctx: SessionContext, evidences: list[dict], used: list[str], t0: float,
        *, hit_type: str, similarity: float = 0.0, reference: str = "",
        entities: list | None = None, intent: str = "",
    ) -> AnswerContext:
        ac = AnswerContext()
        ac.hit_type = hit_type
        ac.similarity = similarity
        ac.entities = entities or []
        ac.intent = intent or "agent"
        ac.reasoning_trace.append({
            "step": 1, "tool": "agent",
            "result": f"启发式/收尾调度 tools={used}, evidence={len(evidences)}",
        })
        llm = get_llm()
        is_mock = isinstance(llm, MockLLM)
        ev_lines = [f"{e.get('ref', '')}｜{e.get('label', '')}｜{(e.get('text', '') or '')[:200]}"
                    for e in evidences]
        history_lines = [
            f"Q: {h.get('question', '')} A: {str(h.get('answer', {}).get('what', ''))[:80]}"
            for h in ctx.history
        ]
        messages = build_synthesis_messages(
            ctx.scene_code, ctx.question, ev_lines, reference, history_lines,
            mock=is_mock, evidence=evidences)
        raw = llm.chat(messages, temperature=0.2, json_mode=not is_mock)
        ac.answer = _parse_answer(raw)
        ac.sources = _sources_from_evidences(evidences)
        ac.review_status = "pending_review"
        ac.elapsed_ms = int((time.time() - t0) * 1000)
        self._persist(ctx, ac)
        return ac

    @staticmethod
    def _user_payload(ctx: SessionContext) -> str:
        hist = [
            {"q": h.get("question"), "a": (h.get("answer") or {}).get("what", "")[:120]}
            for h in ctx.history[-3:]
        ]
        return json.dumps({
            "scene": ctx.scene_code,
            "question": ctx.question,
            "history": hist,
            "instruction": "请调用工具检索后给出 JSON 答案",
        }, ensure_ascii=False)

    def _persist(self, ctx: SessionContext, ac: AnswerContext) -> None:
        entities = ac.entities or []
        norm = normalize_question(ctx.question, ctx.scene_code, entities)
        fp = compute_fingerprint(norm)
        with SessionLocal() as db:
            msg = QaMessage(
                session_id=ctx.session_id, question=ctx.question,
                answer_id="", hit_type=ac.hit_type,
                payload_json={
                    "fingerprint": fp, "question_norm": norm,
                    "answer": ac.answer, "sources": ac.sources,
                    "reasoning_trace": ac.reasoning_trace,
                    "review_status": ac.review_status,
                    "entities": ac.entities, "intent": ac.intent,
                    "similarity": ac.similarity,
                    "orchestrator": "agent",
                })
            db.add(msg)
            db.commit()
            ac.answer_id = msg.id


def _parse_answer(raw: str) -> dict:
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
    except Exception:
        data = {"what": (raw or "").strip()[:500], "why": "", "how": "",
                "caveats": [], "confidence": 0.4, "uncovered": False}
    return {k: data.get(k, "" if k != "caveats" else []) for k in
            ("what", "why", "how", "caveats", "confidence", "uncovered")}


def _trace_summary(result: dict) -> str:
    if result.get("error"):
        return f"error:{result['error']}"[:160]
    if "route" in result:
        return f"{result.get('route')}(sim={result.get('similarity', 0)})"
    if "count" in result:
        return f"{result['count']} hits"
    if "found" in result:
        return f"found={result.get('found')} risk={result.get('risk_level')}"
    if "graph" in result:
        return f"nodes={result['graph'].get('nodes')} edges={result['graph'].get('edges')}"
    return "ok"


def _channel_of(tool_name: str) -> str:
    return {
        "search_doc": "doc", "search_code": "code", "search_mapping": "mapping",
        "search_graph": "graph", "retrieve_all": "doc", "impact_analyze": "graph",
    }.get(tool_name, "doc")


def _to_ev(results: list[dict], default_channel: str) -> list[dict]:
    out = []
    for r in results:
        out.append({
            "channel": r.get("channel") or default_channel,
            "ref": r.get("ref"), "label": r.get("label"),
            "loc": r.get("loc", ""), "obj": r.get("path"),
            "path": r.get("path"), "text": r.get("snippet"),
            "score": r.get("score"), "graph_id": r.get("graph_id"),
        })
    return out


def _sources_from_evidences(evidences: list[dict]) -> list[dict]:
    out, seen = [], set()
    for e in evidences:
        key = (e.get("channel"), e.get("ref"), e.get("path"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "no": len(out) + 1,
            "type": e.get("channel") or "doc",
            "ref": e.get("ref") or "",
            "label": e.get("label") or "",
            "loc": e.get("loc") or "",
            "obj": e.get("obj") or e.get("path") or "",
            "path": e.get("path") or e.get("obj") or "",
            "snippet": (e.get("text") or "")[:160],
            "score": e.get("score") or 0,
        })
        if len(out) >= 12:
            break
    return out


agent_flow = AgentOrchestrator()
