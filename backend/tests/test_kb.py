"""后端自测：指纹/分流、离线管线、问答全链路、复核沉淀、影响分析、代码生成。"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("KB_LLM_API_KEY", "")  # 强制 Mock 模式

_tmp = tempfile.mkdtemp(prefix="kbtest_")
os.environ["KB_PG_DSN"] = ""
import app.db as db_mod  # noqa: E402
from app.db import init_db  # noqa: E402

init_db()

import app.stores.graph as g  # noqa: E402
import app.stores.vector as v  # noqa: E402


def _reset_stores():
    g.graph_store = g.MemGraphStore()
    v.vector_store = v.NumpyVectorStore()
    import app.knowledge.retrieval as r
    r.graph_store = g.graph_store
    r.vector_store = v.vector_store
    import app.qa.analyzer as an
    an.graph_store = g.graph_store
    import app.support as sup
    sup.graph_store = g.graph_store
    import app.seed as seed_mod
    seed_mod.graph_store = g.graph_store
    import app.ingest.pipeline as pl
    pl.graph_store = g.graph_store
    pl.vector_store = v.vector_store
    with db_mod.SessionLocal() as db2:
        db2.query(db_mod.VerifiedAnswer).delete()
        db2.query(db_mod.QaMessage).delete()
        db2.commit()


def test_fingerprint_and_route():
    from app.knowledge.fingerprint import compute_fingerprint, normalize_question, route_by_similarity
    n1 = normalize_question("ATM取款 错误码14 余额不足 怎么排查？", "ATM", ["错误码14"])
    n2 = normalize_question("ATM取款 错误码14 余额不足 怎么排查", "ATM", ["错误码14"])
    assert compute_fingerprint(n1) == compute_fingerprint(n2)
    assert route_by_similarity(1.0) == "exact"
    assert route_by_similarity(0.87) == "similar"
    assert route_by_similarity(0.3) == "miss"


def test_seed_and_ingest():
    _reset_stores()
    from app.seed import seed_knowledge
    result = seed_knowledge(force=True)
    assert not result.get("skipped")
    stats = g.graph_store.stats()
    assert stats["nodes"] > 30, stats
    assert stats["by_label"].get("ErrorCode", 0) >= 7
    assert stats["by_label"].get("CardType", 0) >= 6
    assert v.vector_store.count("kb_doc_chunk") > 5
    assert v.vector_store.count("kb_code_chunk") >= 5
    assert v.vector_store.count("kb_mapping_chunk") >= 1


def test_qa_flow_full():
    _reset_stores()
    from app.seed import seed_knowledge
    seed_knowledge(force=True)
    from app.qa.flow import SessionContext, flow
    ctx = SessionContext(session_id="s-test", question="ATM取款返回错误码14余额不足，应如何排查处理？")
    ac = flow.run(ctx)
    assert ac.hit_type == "miss"
    assert ac.answer.get("what")
    assert ac.sources, "答案必须带溯源"
    assert any(s["type"] == "graph" or "错误码" in s["ref"] for s in ac.sources)
    assert ac.review_status == "pending_review"
    assert ac.answer_id

    # 复核入库
    from app.knowledge import cache as kcache
    with db_mod.SessionLocal() as db2:
        from app.db import QaMessage
        m = db2.get(QaMessage, ac.answer_id)
        p = m.payload_json
    aid = kcache.save_verified(fingerprint=p["fingerprint"], question_norm=p["question_norm"],
                               scene_code="ATM", answer=ac.answer, sources=ac.sources,
                               hit_type="miss", verified_by="gov01", kb_version="v0",
                               question=ctx.question)
    assert aid

    # 同题再问 → 精确命中
    ctx2 = SessionContext(session_id="s-test",
                          question="ATM取款返回错误码14余额不足，应如何排查处理？",
                          history=[{"question": ctx.question, "answer": ac.answer, "entities": ac.entities}])
    ac2 = flow.run(ctx2)
    assert ac2.hit_type == "exact", ac2.hit_type
    assert ac2.review_status == "verified"


def test_followup_and_impact():
    _reset_stores()
    from app.seed import seed_knowledge
    seed_knowledge(force=True)
    from app.qa.flow import SessionContext, flow
    ac1 = flow.run(SessionContext(session_id="s-fu", question="错误码14是什么意思？"))
    assert ac1.sources
    ac2 = flow.run(SessionContext(session_id="s-fu", question="那境外卡取款有什么区别？",
                                  history=[{"question": "错误码14是什么意思？",
                                            "answer": ac1.answer, "entities": ac1.entities}]))
    assert ac2.answer.get("what")

    from app.support import analyze_impact, generate_skeleton
    imp = analyze_impact("ATMWD402", "余额校验逻辑调整")
    assert imp["found"] and imp["affected"]["total"] > 0
    assert imp["risk_level"] in ("low", "medium", "high")

    code = generate_skeleton("ATM取款接口", "spring_controller")
    assert code["files"][0]["language"] == "java"
    assert code["disclaimer"]
    assert code["files"][0]["review_points"]


def test_governance_apply():
    _reset_stores()
    from app.seed import seed_knowledge
    seed_knowledge(force=True)
    from app.db import GovernTask, SessionLocal
    from app.ingest.pipeline import apply_tag_review
    with SessionLocal() as db2:
        t = db2.query(GovernTask).first()
        assert t is not None
        task_id = t.id
        first = t.items_json[0]["item_id"]
    result = apply_tag_review(task_id, [{"item_id": first, "action": "accept"}], "gov01")
    assert result["applied"] == 1
    # 标签节点写入图谱
    assert g.graph_store.find("Tag", verified=True)


def test_vocab_and_doc_linker():
    _reset_stores()
    from app.seed import seed_knowledge
    seed_knowledge(force=True)
    from app.ingest.tagger import ensure_vocab, get_vocab, link_doc_evidence
    ensure_vocab()
    vocab = get_vocab()
    assert "取款" in vocab.get("功能域", []) and "conflict" in vocab.get("治理", [])
    # S2 文档链接：ATMWD402 在业务流程文档中被提及
    ev = link_doc_evidence("ATMWD402")
    assert ev, "应能找到文档对 ATMWD402 的提及"
    assert any("atm_withdraw_flow" in e["path"] for e in ev)
    assert all(e["excerpt"] for e in ev)
    # Mock LLM 下交叉打标应优雅跳过
    from app.ingest.tagger import cross_tag_units
    r = cross_tag_units(limit=3)
    assert r.get("skipped") is True
