"""工具层与 Agent 启发式编排自测。"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("KB_LLM_API_KEY", "")

_tmp = tempfile.mkdtemp(prefix="kbtools_")
os.environ["KB_PG_DSN"] = ""

from app.db import init_db  # noqa: E402

init_db()


def test_tool_handlers_basic():
    from app.seed import seed_knowledge
    from app.tools.handlers import invoke_tool, list_tools

    seed_knowledge(force=True)
    names = {t["name"] for t in list_tools()}
    assert {"search_doc", "search_code", "search_graph", "query_cache"} <= names

    doc = invoke_tool("search_doc", {"query": "错误码14", "top_k": 3})
    assert doc.get("count", 0) >= 0
    assert "results" in doc

    graph = invoke_tool("search_graph", {"query": "错误码14", "intent": "business_rule"})
    assert "results" in graph

    stats = invoke_tool("kb_stats", {})
    assert stats["graph"]["nodes"] > 0


def test_agent_heuristic_ask():
    from app.db import SessionLocal, VerifiedAnswer
    from app.qa.flow import SessionContext
    from app.seed import seed_knowledge
    from app.tools.agent import agent_flow

    seed_knowledge(force=True)
    with SessionLocal() as db:
        db.query(VerifiedAnswer).delete()
        db.commit()

    ctx = SessionContext(
        session_id="s-agent",
        question="ATM取款返回错误码14余额不足，应如何排查处理？",
    )
    ac = agent_flow.run(ctx)
    assert ac.answer.get("what")
    assert ac.sources
    tools_used = {t["tool"] for t in ac.reasoning_trace}
    assert "query_cache" in tools_used or "analyze_question" in tools_used or "agent" in tools_used
    assert ac.answer_id
