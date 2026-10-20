"""问答 / 检索 / 溯源 / 复核路由（设计 7.2-7.5 节）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from ..db import KbVersion, QaMessage, QaSession, SessionLocal, User, VerifiedAnswer
from ..deps import audit, current_user, require_roles
from ..knowledge import cache, retrieval
from ..qa.flow import SessionContext, flow
from ..response import KbError, ok
from ..stores.graph import graph_store

router = APIRouter(prefix="/qa", tags=["qa"])
search_router = APIRouter(prefix="/search", tags=["search"])


class AskIn(BaseModel):
    session_id: str
    question: str
    top_k: int = 5
    with_reasoning: bool = True


class FollowupIn(BaseModel):
    session_id: str
    answer_id: str
    question: str


def _history(session_id: str) -> list[dict]:
    with SessionLocal() as db:
        msgs = db.execute(select(QaMessage).where(QaMessage.session_id == session_id)
                          .order_by(QaMessage.created_at)).scalars().all()
    out = []
    for m in msgs[-4:]:
        p = m.payload_json or {}
        out.append({"question": m.question, "answer": p.get("answer", {}),
                    "entities": p.get("entities", [])})
    return out


def _payload(ac) -> dict:
    return {
        "answer_id": ac.answer_id,
        "hit_type": ac.hit_type,
        "similarity": ac.similarity,
        "intent": ac.intent,
        "entities": ac.entities,
        "answer": ac.answer,
        "sources": ac.sources,
        "reasoning_trace": ac.reasoning_trace,
        "review_status": ac.review_status,
        "elapsed_ms": ac.elapsed_ms,
    }


@router.post("/sessions")
def create_session(request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        s = QaSession(scene_code="ATM", user=user.username)
        db.add(s)
        db.commit()
        return ok({"session_id": s.id, "scene_code": s.scene_code}, request)


@router.post("/ask")
def ask(body: AskIn, request: Request, user: User = Depends(current_user)):
    if not body.question.strip():
        raise KbError("40001", "question 不能为空")
    ctx = SessionContext(session_id=body.session_id, user=user.username,
                         question=body.question.strip(), history=_history(body.session_id))
    ac = flow.run(ctx)
    audit(request, user.username, "qa_ask", obj=body.question[:100],
          detail={"hit_type": ac.hit_type, "answer_id": ac.answer_id})
    return ok(_payload(ac), request)


class AskAgentIn(BaseModel):
    session_id: str
    question: str
    mode: str = "agent"  # agent | flow


@router.post("/ask_agent")
def ask_agent(body: AskAgentIn, request: Request, user: User = Depends(current_user)):
    """Agent 模式：由模型/启发式自动调度 search_doc/search_code/search_graph 等工具。"""
    if not body.question.strip():
        raise KbError("40001", "question 不能为空")
    ctx = SessionContext(session_id=body.session_id, user=user.username,
                         question=body.question.strip(), history=_history(body.session_id))
    if body.mode == "flow":
        ac = flow.run(ctx)
        orch = "flow"
    else:
        from ..tools.agent import agent_flow
        ac = agent_flow.run(ctx)
        orch = "agent"
    audit(request, user.username, "qa_ask_agent", obj=body.question[:100],
          detail={"hit_type": ac.hit_type, "answer_id": ac.answer_id, "orchestrator": orch})
    data = _payload(ac)
    data["orchestrator"] = orch
    return ok(data, request)


@router.get("/tools")
def qa_tools(request: Request, user: User = Depends(current_user)):
    """列出可供 Agent / MCP 调度的工具清单。"""
    from ..tools.handlers import list_tools
    return ok({"tools": list_tools(), "mcp": "python -m app.mcp_server"}, request)


@router.post("/followup")
def followup(body: FollowupIn, request: Request, user: User = Depends(current_user)):
    ctx = SessionContext(session_id=body.session_id, user=user.username,
                         question=body.question.strip(), history=_history(body.session_id))
    ac = flow.run(ctx)
    audit(request, user.username, "qa_followup", obj=body.question[:100],
          detail={"hit_type": ac.hit_type, "answer_id": ac.answer_id})
    return ok(_payload(ac), request)


@router.get("/sessions/{session_id}/history")
def history(session_id: str, request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        msgs = db.execute(select(QaMessage).where(QaMessage.session_id == session_id)
                          .order_by(QaMessage.created_at)).scalars().all()
    return ok([{"message_id": m.id, "question": m.question, "hit_type": m.hit_type,
                "answer": (m.payload_json or {}).get("answer", {}),
                "sources": (m.payload_json or {}).get("sources", []),
                "created_at": m.created_at.isoformat()} for m in msgs], request)


@router.get("/answers/{answer_id}/sources")
def sources(answer_id: str, request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        m = db.get(QaMessage, answer_id)
        if m is not None:
            srcs = (m.payload_json or {}).get("sources", [])
            return ok({"answer_id": answer_id, "sources": srcs}, request)
        v = db.get(VerifiedAnswer, answer_id)
        if v is not None:
            return ok({"answer_id": answer_id, "sources": v.sources_json or [],
                       "kb_version": v.kb_version, "verified_by": v.verified_by}, request)
    raise KbError("40401", "答案不存在")


@router.get("/sources/preview")
def source_preview(
    request: Request,
    user: User = Depends(current_user),
    path: str = "",
    type: str = "doc",
    ref: str = "",
    loc: str = "",
    obj: str = "",
    label: str = "",
    snippet: str = "",
    answer_id: str = "",
    no: int = 0,
):
    """点击依据来源：弹出文档预览所需的全文/图谱详情。"""
    from ..qa.source_view import preview_source

    # 优先从答案溯源条目还原完整字段
    if answer_id and no:
        with SessionLocal() as db:
            m = db.get(QaMessage, answer_id)
            srcs = []
            if m is not None:
                srcs = (m.payload_json or {}).get("sources") or []
            else:
                v = db.get(VerifiedAnswer, answer_id)
                if v is not None:
                    srcs = v.sources_json or []
            hit = next((s for s in srcs if int(s.get("no", -1)) == int(no)), None)
            if hit:
                path = path or hit.get("path") or hit.get("obj") or ""
                type = type if type != "doc" else hit.get("type", type)
                ref = ref or hit.get("ref", "")
                loc = loc or hit.get("loc", "")
                obj = obj or hit.get("obj", "")
                label = label or hit.get("label", "")
                snippet = snippet or hit.get("snippet", "")

    doc = preview_source(
        path=path, source_type=type, ref=ref, loc=loc,
        snippet=snippet, obj=obj, label=label,
    )
    if not doc.get("available") and not doc.get("content"):
        raise KbError("40401", "未找到依据文档")
    return ok(doc, request)


class ReviewIn(BaseModel):
    verdict: str  # approved / rejected
    corrected_answer: dict | None = None
    fingerprint_scope: str = "scene:ATM"


@router.post("/answers/{answer_id}/review")
def review_answer(answer_id: str, body: ReviewIn, request: Request,
                  user: User = Depends(require_roles("gov", "admin", "biz", "arch"))):
    with SessionLocal() as db:
        m = db.get(QaMessage, answer_id)
        if m is None:
            raise KbError("40401", "答案不存在")
        p = m.payload_json or {}
        if body.verdict != "approved":
            p["review_status"] = "rejected"
            m.payload_json = p
            db.commit()
            audit(request, user.username, "answer_reject", answer_id)
            return ok({"answer_id": answer_id, "status": "rejected"}, request)
        answer = body.corrected_answer or p.get("answer", {})
        ver = db.execute(select(KbVersion).order_by(KbVersion.id.desc())).scalar()
        kb_version = ver.version_no if ver else "v0"
        aid = cache.save_verified(
            fingerprint=p["fingerprint"], question_norm=p["question_norm"],
            scene_code="ATM", answer=answer, sources=p.get("sources", []),
            hit_type=m.hit_type, verified_by=user.username, kb_version=kb_version,
            question=m.question)
        p["review_status"] = "verified"
        m.payload_json = p
        db.commit()
        audit(request, user.username, "answer_approve", answer_id,
              detail={"verified_answer_id": aid})
        return ok({"answer_id": answer_id, "status": "verified",
                   "verified_answer_id": aid, "kb_version": kb_version}, request)


# ---------------------------------------------------------------- 检索接口
class GraphSearchIn(BaseModel):
    query: str = ""
    mode: str = "entity"  # entity | impact | three_layer
    params: dict = {}
    top_k: int = 20


def _resolve(name: str) -> str:
    nodes = graph_store.find_by_name(name)
    return nodes[0]["id"] if nodes else name


@search_router.post("/graph")
def graph_search(body: GraphSearchIn, request: Request, user: User = Depends(current_user)):
    params = body.params or {}
    if body.mode == "impact":
        target = params.get("entity") or body.query
        sub = graph_store.impact(_resolve(target), depth=int(params.get("depth", 3)))
        root = sub.pop("root", None)
        return ok({"nodes": [root] if root else [], "edges": [], "impact": sub,
                   "render_hint": "topology"}, request)
    if body.mode == "three_layer":
        data = graph_store.three_layer(params.get("fp") or body.query)
        return ok({"nodes": data["nodes"], "edges": data["edges"],
                   "render_hint": "topology"}, request)
    ents = retrieval.graph_evidence([body.query or params.get("entity", "")], "business_rule")
    return ok({"evidences": ents, "render_hint": "list"}, request)


class VectorSearchIn(BaseModel):
    query: str
    collections: list[str] = ["kb_doc_chunk"]
    top_k: int = 5


@search_router.post("/vector")
def vector_search(body: VectorSearchIn, request: Request, user: User = Depends(current_user)):
    ev = retrieval.vector_evidence(body.query, body.collections, body.top_k)
    return ok({"evidences": ev}, request)
