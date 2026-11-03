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
from ..qa.answers import ANSWER_GUIDANCE, parse_answer, repair_answer
from ..qa import analyzer
from ..knowledge.evidence import EvidenceRegistry, normalize
from ..knowledge.scope import question_scoped, active_scope
from .handlers import dumps_result, invoke_tool, openai_tools, tool_retrieve_all

MAX_ROUNDS = 6

SYSTEM_PROMPT = """你是某行核心系统迁移知识库助手。你必须通过工具检索证据后再回答，禁止编造。

可用策略：
0) 首条消息已附带服务端按原问题召回的证据。足够回答时直接作答，不为填满数量而继续查找；
1) 先 analyze_question，再 query_cache；
2) exact 命中则可直接整理答案；
3) 否则按需调用 search_graph / search_doc / search_code / search_mapping 或 retrieve_all；
4) 影响面问题用 impact_analyze；需要看原文用 preview_source。

最终必须输出严格 JSON：
{"summary":"直接回答用户的简明答案","what":"...","why":"...","how":"...","caveats":[],"confidence":0.0~1.0,"uncovered":false,"used_tools":["..."]}
why/how 中引用证据时用［1］［2］编号，对应工具结果中的 source_no，禁止自行重新编号。
工具查询只可细化原问题，不能丢掉系统、工程、文件和版本范围。相同 source_no 的补充片段属于同一依据。
原文工具返回的内容只覆盖 loc 指定的行；不要用该编号引用范围外的文件内容。
""" + '\n' + ANSWER_GUIDANCE


class AgentOrchestrator:
    """LLM 自动调度工具的问答编排器。"""

    @question_scoped
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
        if active_scope() and active_scope().plan:
            messages[0]['content'] += '\n' + active_scope().plan.guidance
        used: list[str] = []
        evidences: list[dict] = []
        # Deterministic recall keeps the original subject even if the model omits it in later tools.
        initial = invoke_tool('retrieve_all', {'query': ctx.question, 'top_k': 5,
                                              'intent': analyzer.classify_intent(ctx.question)})
        _collect_evidence(initial, 'retrieve_all', evidences)
        used.append('retrieve_all')
        ac.reasoning_trace.append({'step': 1, 'tool': 'retrieve_all', 'result': _trace_summary(initial)})
        ac.entities = initial.get('entities') or []
        ac.intent = initial.get('intent') or analyzer.classify_intent(ctx.question)
        messages[1]['content'] += '\n服务端初始证据（source_no 为全会话本轮稳定编号）：\n' + dumps_result(initial)

        for round_i in range(MAX_ROUNDS):
            resp = llm.chat_tools(messages, tools=openai_tools(), temperature=0.1)
            tool_calls = resp.get("tool_calls") or []
            content = resp.get("content") or ""

            if tool_calls:
                assistant_message = {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tool_calls,
                }
                if "reasoning_content" in resp:
                    assistant_message["reasoning_content"] = resp["reasoning_content"]
                messages.append(assistant_message)
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except json.JSONDecodeError:
                        args = {}
                    if name in {'query_cache', 'analyze_question'}:
                        args['question'] = active_scope().question if active_scope() else ctx.question
                        if name == 'query_cache':
                            args['scene_code'] = ctx.scene_code
                    result = invoke_tool(name, args)
                    used.append(name)
                    ac.reasoning_trace.append({
                        "step": len(ac.reasoning_trace) + 1,
                        "tool": name,
                        "result": _trace_summary(result),
                    })
                    # 收集证据供溯源
                    _collect_evidence(result, name, evidences)
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
                        "content": dumps_result(result),
                    })
                continue

            # 无 tool_calls → 最终答案
            answer = _parse_answer(content)
            ac.answer, ac.sources = repair_answer(llm, answer, EvidenceRegistry(evidences).sources(include_text=True), ctx.question)
            ac.hit_type = ac.hit_type or "miss"
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
        q = active_scope().question if active_scope() else ctx.question
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
        # The model-free path uses the same generic retriever as Flow and MCP.
        # No project names or business-scene rules decide whether code is searched.
        retrieved = invoke_tool('retrieve_all', {
            'query': analysis.get('rewritten') or q,
            'intent': ac.intent or 'business_rule', 'entities': ac.entities,
        })
        used.append('retrieve_all')
        evidences = _to_ev(retrieved.get('results') or [], 'doc')

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
        from ..knowledge.retrieval import fuse_and_rerank
        evidences = fuse_and_rerank(ctx.question, evidences)
        ac.entities = entities or []
        ac.intent = intent or "agent"
        ac.reasoning_trace.append({
            "step": 1, "tool": "agent",
            "result": f"启发式/收尾调度 tools={used}, evidence={len(evidences)}",
        })
        llm = get_llm()
        is_mock = isinstance(llm, MockLLM)
        ev_lines = [f"{e.get('ref', '')}｜{e.get('label', '')} {e.get('loc', '')}｜{e.get('text', '') or ''}"
                    for e in evidences]
        history_lines = [
            f"Q: {h.get('question', '')} A: {str(h.get('answer', {}).get('what', ''))[:80]}"
            for h in ctx.history
        ]
        messages = build_synthesis_messages(
            ctx.scene_code, ctx.question, ev_lines, reference, history_lines,
            mock=is_mock, evidence=evidences)
        raw = llm.chat(messages, temperature=0.2, json_mode=not is_mock)
        ac.answer, ac.sources = repair_answer(llm, _parse_answer(raw), EvidenceRegistry(evidences).sources(include_text=True), ctx.question)
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
        norm = normalize_question(active_scope().question if active_scope() else ctx.question, ctx.scene_code, entities)
        fp = compute_fingerprint(norm)
        with SessionLocal() as db:
            msg = QaMessage(
                session_id=ctx.session_id, question=ctx.question,
                answer_id="", hit_type=ac.hit_type,
                payload_json={
                    "fingerprint": fp, "question_norm": norm,
                    "retrieval_mode": active_scope().plan.mode if active_scope() and active_scope().plan else 'business',
                    "retrieval_diagnostics": active_scope().diagnostics if active_scope() else [],
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
    return parse_answer(raw)


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
    return [normalize(row, default_channel) for row in results]


def _sources_from_evidences(evidences: list[dict]) -> list[dict]:
    return EvidenceRegistry(evidences).sources()


def _collect_evidence(result: dict, name: str, evidences: list[dict]) -> None:
    """Assign stable citation numbers, including source previews seen by the model."""
    rows = result.get('results') or []
    if name == 'preview_source' and result.get('available'):
        rows = [dict(result, channel=result.get('type', 'doc'), ref=result.get('title'),
                     label=result.get('title'), path=result.get('path'), loc=result.get('loc', ''),
                     snippet=result.get('content', ''))]
    for row in rows:
        evidence = _to_ev([row], _channel_of(name))[0]
        row['source_no'] = EvidenceRegistry(evidences).add(evidence)
        scope = active_scope()
        if scope:
            scope.learn(evidence)
        if name == 'preview_source':
            result['source_no'] = row['source_no']


agent_flow = AgentOrchestrator()
