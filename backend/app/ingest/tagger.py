"""双源证据交叉打标（设计：受控词表 + 代码/文档证据融合 + 置信度路由）。

S2 文档实体链接：把文档 chunk 中对程序/交易码的提及绑定为代码单元的证据；
S3 LLM 交叉打标：词表 + 代码节选 + 文档证据 → 标签（含置信度/理由/证据引用）；
路由：confidence ≥ 0.9 自动落图谱（verified, source=ai）；0.4~0.9 进治理任务；
< 0.4 丢弃。Mock LLM 模式下自动跳过（打标依赖真实模型）。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from ..config import settings
from ..db import GovernTask, LabelVocab, SessionLocal
from ..llm import get_llm
from ..stores.graph import graph_store
from ..stores.vector import vector_store

# 受控词表（封闭集）：仅约束 LLM 交叉打标；规则/清洗打标不校验此表
DEFAULT_VOCAB: dict[str, list[str]] = {
    "功能域": ["取款", "余额查询", "余额校验", "手续费计算", "对账", "日终",
             "路由", "制裁筛查", "转账", "出钞控制", "记账", "冲正"],
    "业务对象": ["账户", "报文", "币种", "错误码", "卡种", "队列", "流水号", "利率"],
    "治理": ["conflict", "临时修复", "死代码", "测试开关", "废弃版本", "雷区"],
}

AUTO_ACCEPT = 0.90   # ≥ 此值自动落图谱（抽检）
MIN_KEEP = 0.40      # < 此值丢弃


def ensure_vocab() -> None:
    """启动时补齐 DEFAULT_VOCAB 缺失项（不覆盖已有词条）。"""
    sync_vocab_defaults()


def sync_vocab_defaults() -> dict:
    """将 DEFAULT_VOCAB 中尚未存在的 (category,value) 写入为 approved。"""
    added = 0
    with SessionLocal() as db:
        existing = {
            (r.category, r.value)
            for r in db.execute(select(LabelVocab)).scalars().all()
        }
        for cat, values in DEFAULT_VOCAB.items():
            for v in values:
                if (cat, v) in existing:
                    continue
                db.add(LabelVocab(
                    category=cat, value=v, status="approved", created_by="system"))
                added += 1
        if added:
            db.commit()
    return {"added": added, "default_total": sum(len(v) for v in DEFAULT_VOCAB.values())}


def get_vocab(approved_only: bool = True) -> dict[str, list[str]]:
    with SessionLocal() as db:
        q = select(LabelVocab)
        if approved_only:
            q = q.where(LabelVocab.status == "approved")
        rows = db.execute(q).scalars().all()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r.category, []).append(r.value)
    return out


def is_approved_tag(category: str, value: str) -> bool:
    """标签是否在受控封闭集（approved）内——供 AI 交叉打标使用。"""
    if not category or not value:
        return False
    vocab = get_vocab(approved_only=True)
    return value in vocab.get(category, [])


# ---------------------------------------------------------------- S2 文档链接
def link_doc_evidence(program_name: str, max_ev: int = 4) -> list[dict]:
    """在文档 chunk 中检索对程序的提及，返回证据 [{n, path, excerpt}]。"""
    name = program_name.strip().upper()
    if not name:
        return []
    evidences: list[dict] = []
    for col in ("kb_doc_chunk",):
        for ch in vector_store._data.get(col, []):
            meta = ch["meta"]
            if meta.get("doc_type") not in ("doc", "message_format", "error_code_table"):
                continue
            text = meta.get("text", "")
            idx = text.upper().find(name)
            if idx < 0:
                continue
            start = max(0, idx - 60)
            evidences.append({
                "n": len(evidences) + 1,
                "path": meta.get("source_path", ""),
                "excerpt": text[start:idx + len(name) + 80].replace("\n", " "),
            })
            if len(evidences) >= max_ev:
                return evidences
    return evidences


def _code_excerpt(node_id: str) -> dict:
    """程序节选：注释头 + 段名清单 + 一个代表段代码。"""
    node = graph_store.node(node_id) or {}
    props = node.get("props", {})
    sections: list[str] = []
    sample_text = ""
    prog = props.get("name", "")
    for ch in vector_store._data.get("kb_code_chunk", []):
        cu = str(ch["meta"].get("code_unit", ""))
        if not cu.startswith(prog + "."):
            continue
        sections.append(cu.split(".", 1)[1])
        if not sample_text:
            sample_text = ch["meta"].get("text", "")[:1200]
    _, edges = graph_store.neighbors(node_id, max_hops=1, rels={"CALLS", "READS", "WRITES", "PART_OF"})
    calls = sorted({e["dst"].split("/")[-1] for e in edges if e["rel"] == "CALLS"})
    tables = sorted({e["dst"].split("/")[-1] for e in edges if e["rel"] in ("READS", "WRITES")})
    return {
        "program": prog,
        "lang": props.get("lang", "COBOL"),
        "loc": props.get("loc", 0),
        "comment_head": props.get("comment_head", ""),
        "sections": sections[:24],
        "calls": calls[:15],
        "tables": tables[:10],
        "section_sample": sample_text,
    }


TAG_SYSTEM_PROMPT = (
    "你是遗留代码知识治理助手。任务：依据【代码结构】与【文档证据】为程序打业务标签。\n"
    "硬性规则：1) 标签只能从 label_vocab 中选择，禁止发明新标签；"
    "2) 每个标签给出 confidence(0~1)、reason、evidence（引用编号列表，代码证据写 code:程序名）；"
    "3) 文档与代码行为矛盾时打 治理:conflict 标签；"
    "4) 证据不足不要硬打标签，宁缺毋滥。\n"
    '输出严格 JSON：{"tags": [{"category": str, "value": str, "confidence": float, '
    '"reason": str, "evidence": [str]}]}'
)


def _parse_tags(raw: str) -> list[dict]:
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
        return data.get("tags", []) if isinstance(data, dict) else []
    except Exception:
        return []


# ---------------------------------------------------------------- S3 交叉打标
def cross_tag_units(limit: int = 8) -> dict:
    """对程序级 CodeUnit 执行交叉打标；返回统计。Mock 模式直接跳过。"""
    llm = get_llm()
    if type(llm).__name__ != "ApiLLM":
        return {"skipped": True, "reason": "LLM 为 Mock 模式，交叉打标需真实模型"}
    vocab = get_vocab(approved_only=True)
    if not vocab:
        return {"skipped": True, "reason": "标签词表为空"}
    units = [n for n in graph_store.find("CodeUnit", kind="program")]
    stats = {"units": 0, "auto_applied": 0, "pending_items": 0, "dropped": 0, "detail": []}
    pending_items: list[dict] = []
    for unit in units[:limit]:
        prog = unit["props"].get("name", "")
        code = _code_excerpt(unit["id"])
        doc_ev = link_doc_evidence(prog)
        payload = {
            "label_vocab": vocab,
            "code": code,
            "doc_evidence": doc_ev,
        }
        try:
            raw = llm.chat(
                [{"role": "system", "content": TAG_SYSTEM_PROMPT},
                 {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                temperature=0.1, json_mode=True)
            tags = _parse_tags(raw)
        except Exception as e:
            stats["detail"].append({"program": prog, "error": str(e)[:120]})
            continue
        stats["units"] += 1
        valid_values = {(c, v) for c, vs in vocab.items() for v in vs}
        for t in tags[:6]:
            conf = float(t.get("confidence", 0) or 0)
            cat, val = t.get("category", ""), t.get("value", "")
            if (cat, val) not in valid_values or conf < MIN_KEEP:
                stats["dropped"] += 1
                continue
            entry = {
                "node_id": unit["id"], "node_name": prog,
                "tag": {"category": cat, "value": val},
                "source": "ai", "confidence": round(conf, 2),
                "reason": str(t.get("reason", ""))[:200],
                "evidence": [str(e)[:160] for e in (t.get("evidence") or [])][:4],
                "doc_evidence": doc_ev[:2],
                "status": "pending",
            }
            if conf >= AUTO_ACCEPT:
                _apply_tag(entry, verified=True)
                entry["status"] = "auto_applied"
                stats["auto_applied"] += 1
            else:
                pending_items.append(entry)
                stats["pending_items"] += 1
        stats["detail"].append({"program": prog, "tags": len(tags),
                                "doc_evidence": len(doc_ev)})
    if pending_items:
        with SessionLocal() as db:
            task = GovernTask(
                task_type="cross_tagging",
                title=f"[AI交叉打标] 代码×文档对照（{len(pending_items)} 条待校对）",
                items_json=[{**it, "item_id": f"xtag_{i+1:04d}"}
                            for i, it in enumerate(pending_items)],
                status="pending")
            db.add(task)
            db.commit()
    return stats


def _apply_tag(entry: dict, verified: bool) -> None:
    """AI 自动落标专用；调用前应已通过 valid_values 过滤。"""
    tag = entry["tag"]
    if entry.get("source") == "ai" and not is_approved_tag(
            tag.get("category", ""), tag.get("value", "")):
        return
    tid = graph_store.upsert_node(
        f"tag/{tag['category']}:{tag['value']}", "Tag",
        {"name": f"{tag['category']}:{tag['value']}", "category": tag["category"],
         "value": tag["value"], "source": entry.get("source", "ai"),
         "verified": verified})
    graph_store.upsert_edge(entry["node_id"], "TAGGED", tid,
                            {"confidence": entry.get("confidence"),
                             "reason": entry.get("reason", ""),
                             "auto": verified})
    graph_store.save()
