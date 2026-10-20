"""支撑路由：影响分析 / 代码生成 / 版本 / 工具注册 / 健康与状态（设计 7.7-7.9、6 章）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from ..db import KbVersion, SessionLocal, ToolSpec as ToolSpecRow, User
from ..deps import audit, current_user, require_roles
from ..llm import llm_status
from ..code_work import get_work, save_annotate, save_spec
from ..prompt_config import get_prompt, list_prompts, reset_prompt, update_prompt
from ..response import KbError, ok
from ..stores.graph import graph_store
from ..stores.vector import vector_store
from ..code_tree import build_code_tree, preview_source
from ..support import analyze_impact, generate_skeleton
from ..support_annotate import annotate_code
from ..support_spec import generate_spec, infer_prompt_type

router = APIRouter(tags=["support"])


@router.get("/health")
def health():
    return {"status": "up", "service": "hf-kb"}


@router.get("/admin/llm-status")
def get_llm_status(request: Request, user: User = Depends(current_user)):
    return ok(llm_status(), request)


@router.get("/admin/kb-stats")
def kb_stats(request: Request, user: User = Depends(current_user)):
    return ok({"graph": graph_store.stats(), "vector": vector_store.stats()}, request)


@router.get("/graph/struct")
def graph_struct(request: Request, user: User = Depends(current_user)):
    """图谱全量结构（节点/边/统计），供前端拓扑可视化渲染。"""
    dump = graph_store.dump()
    nodes = [
        {"id": n["id"], "label": n["label"],
         "name": n["props"].get("name", n["id"]),
         "props": {k: v for k, v in n["props"].items()
                   if k in ("code", "meaning", "action", "level", "caliber",
                            "desc", "kind", "lang", "rule", "type", "system",
                            "category", "value", "direction", "protocol",
                            "effective_date", "complexity", "loc")}}
        for n in dump["nodes"][:1500]
    ]
    edges = [{"src": e["src"], "rel": e["rel"], "dst": e["dst"]}
             for e in dump["edges"][:3000]]
    return ok({"nodes": nodes, "edges": edges, "stats": graph_store.stats()}, request)


@router.get("/admin/prompts")
def admin_list_prompts(request: Request, user: User = Depends(current_user)):
    return ok(list_prompts(), request)


@router.get("/admin/prompts/{prompt_type}")
def admin_get_prompt(prompt_type: str, request: Request,
                     user: User = Depends(current_user)):
    return ok(get_prompt(prompt_type), request)


class PromptUpdateIn(BaseModel):
    title: str | None = None
    system_prompt: str | None = None
    enabled: bool | None = None


@router.put("/admin/prompts/{prompt_type}")
def admin_update_prompt(prompt_type: str, body: PromptUpdateIn, request: Request,
                        user: User = Depends(require_roles("gov", "admin"))):
    result = update_prompt(
        prompt_type,
        title=body.title,
        system_prompt=body.system_prompt,
        enabled=body.enabled,
        actor=user.username,
    )
    audit(request, user.username, "prompt_update", prompt_type,
          detail={"enabled": result.get("enabled")})
    return ok(result, request)


@router.post("/admin/prompts/{prompt_type}/reset")
def admin_reset_prompt(prompt_type: str, request: Request,
                       user: User = Depends(require_roles("gov", "admin"))):
    result = reset_prompt(prompt_type, actor=user.username)
    audit(request, user.username, "prompt_reset", prompt_type)
    return ok(result, request)


@router.get("/admin/tools")
def tools(request: Request, user: User = Depends(current_user)):
    from ..qa.flow import registry
    with SessionLocal() as db:
        extra = db.execute(select(ToolSpecRow)).scalars().all()
    specs = registry.specs()
    specs += [t.spec_json for t in extra if t.enabled]
    return ok(specs, request)


class ToolRegisterIn(BaseModel):
    name: str
    description: str = ""
    input_schema: dict = {}
    timeout_ms: int = 3000
    idempotent: bool = True


@router.post("/admin/tools/register")
def register_tool(body: ToolRegisterIn, request: Request,
                  user: User = Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(ToolSpecRow, body.name)
        if row is None:
            row = ToolSpecRow(name=body.name)
            db.add(row)
        row.spec_json = body.model_dump()
        db.commit()
    audit(request, user.username, "tool_register", body.name)
    return ok({"name": body.name, "registered": True}, request)


class ImpactIn(BaseModel):
    change_type: str = "code"  # code | interface | rule
    target: str
    change_summary: str = ""
    depth: int = 3


@router.post("/impact/analyze")
def impact_analyze(body: ImpactIn, request: Request, user: User = Depends(current_user)):
    result = analyze_impact(body.target, body.change_summary, body.depth)
    audit(request, user.username, "impact_analyze", body.target,
          detail={"risk": result.get("risk_level")})
    return ok(result, request)


class CodegenIn(BaseModel):
    target: str = "spring_controller"  # spring_controller | python_script
    interface_id: str
    options: dict = {}


@router.post("/codegen/skeleton")
def codegen(body: CodegenIn, request: Request, user: User = Depends(current_user)):
    result = generate_skeleton(body.interface_id, body.target)
    audit(request, user.username, "codegen", body.interface_id)
    return ok(result, request)


class AnnotateIn(BaseModel):
    code: str
    language: str = "cobol"
    hint: str = ""
    path: str = ""
    symbol: str = ""


@router.post("/codegen/annotate")
def codegen_annotate(body: AnnotateIn, request: Request, user: User = Depends(current_user)):
    if not (body.code or "").strip():
        raise KbError("40001", "code 不能为空")
    result = annotate_code(body.code, body.language or "cobol", body.hint or "")
    saved = save_annotate(
        path=body.path or "",
        symbol=body.symbol or "",
        language=body.language or "cobol",
        hint=body.hint or "",
        source_code=body.code,
        annotate_result=result,
        actor=user.username,
    )
    result["work_id"] = saved.get("id")
    result["saved"] = True
    audit(request, user.username, "codegen_annotate",
          detail={"language": body.language, "path": body.path,
                  "len": len(body.code),
                  "entities": (result.get("entities") or [])[:8]})
    return ok(result, request)


class SpecIn(BaseModel):
    code: str = ""
    annotated_code: str = ""
    prompt_type: str = ""
    path: str = ""
    symbol: str = ""
    language: str = "cobol"
    hint: str = ""


@router.post("/codegen/spec")
def codegen_spec(body: SpecIn, request: Request, user: User = Depends(current_user)):
    ann = (body.annotated_code or "").strip()
    if not ann:
        # 尝试从本地库取已保存注释
        work = get_work(body.path or "", body.symbol or "")
        if work and work.get("annotated_code"):
            ann = work["annotated_code"]
            annotate_payload = work.get("annotate") or {}
        else:
            raise KbError("40001", "请先生成注释后再生成式样书")
    else:
        work = get_work(body.path or "", body.symbol or "")
        annotate_payload = (work or {}).get("annotate") or {}

    ptype = (body.prompt_type or "").strip() or infer_prompt_type(
        body.path or "", body.language or "")
    result = generate_spec(
        body.code or "",
        prompt_type=ptype,
        path=body.path or "",
        language=body.language or "",
        hint=body.hint or "",
        annotated_code=ann,
        annotate_payload=annotate_payload,
    )
    saved = save_spec(
        path=body.path or "",
        symbol=body.symbol or "",
        language=body.language or "cobol",
        hint=body.hint or "",
        prompt_type=ptype,
        spec_result=result,
        actor=user.username,
    )
    result["work_id"] = saved.get("id")
    result["saved"] = True
    audit(request, user.username, "codegen_spec",
          detail={"prompt_type": result.get("prompt_type"),
                  "path": body.path, "len": len(ann)})
    return ok(result, request)


@router.get("/codegen/work")
def codegen_work(request: Request, path: str, symbol: str = "",
                 user: User = Depends(current_user)):
    data = get_work(path, symbol)
    return ok(data or {"path": path, "symbol": symbol, "has_annotate": False,
                       "has_spec": False}, request)


@router.get("/kb/code-tree")
def kb_code_tree(request: Request, user: User = Depends(current_user)):
    return ok(build_code_tree(), request)


@router.get("/kb/code-tree/preview")
def kb_code_tree_preview(request: Request, path: str, symbol: str = "",
                         user: User = Depends(current_user)):
    try:
        data = preview_source(path, symbol)
    except ValueError as exc:
        raise KbError("40001", str(exc)) from exc
    return ok(data, request)


@router.get("/kb/versions")
def versions(request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        rows = db.execute(select(KbVersion).order_by(KbVersion.id.desc()).limit(50)).scalars().all()
    return ok([{"id": r.id, "version_no": r.version_no, "change_note": r.change_note,
                "changed_objs": len(r.changed_objs or []), "created_by": r.created_by,
                "created_at": r.created_at.isoformat()} for r in rows], request)


@router.get("/kb/versions/{version_id}")
def version_detail(version_id: int, request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        r = db.get(KbVersion, version_id)
    if r is None:
        raise KbError("40401", "版本不存在")
    return ok({"id": r.id, "version_no": r.version_no, "change_note": r.change_note,
               "changed_objs": (r.changed_objs or [])[:200],
               "created_by": r.created_by, "created_at": r.created_at.isoformat()}, request)
