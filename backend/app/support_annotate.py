"""基于知识库为粘贴代码生成注释（检索证据 + LLM；Mock 启发式回退）。"""
from __future__ import annotations

import json
import re
from typing import Any

from .knowledge.retrieval import retrieve
from .llm import get_llm

DISCLAIMER = "注释由知识库辅助生成，需人工复核后合入；不得视为已验证业务口径。"

_ANNOTATE_SYSTEM = """你是遗留系统代码注释助手。任务：依据【知识库证据】为用户粘贴的代码补充注释。
硬性规则：
1) 只添加注释，禁止修改、删除或重排任何可执行语句/逻辑；
2) 事实性说明必须引用证据编号，如 [1][2]；证据不足处用 TODO[KB] 标明，勿编造；
3) COBOL 用整行 * 注释；其他语言用该语言惯用行注释；
4) 优先在段名/关键 CALL/校验/记账等位置前插入简短块注释。
输出严格 JSON：
{"annotated_code": str, "notes": [str], "uncovered": bool}
"""


def _extract_symbols(code: str, hint: str = "") -> tuple[str, list[str]]:
    """从代码抽取检索用符号与实体列表。"""
    entities: list[str] = []
    if hint.strip():
        entities.append(hint.strip())

    m = re.search(r"PROGRAM-ID\.\s*([A-Z0-9_-]+)", code, re.I)
    if m:
        entities.append(m.group(1).upper())

    for sec in re.findall(r"^\s*([0-9]{4}-[A-Z0-9-]+)\s*\.", code, re.M | re.I):
        entities.append(sec.upper())
        if len(entities) > 14:
            break

    for callee in re.findall(r"\bCALL\s+'([A-Z0-9_-]+)'", code, re.I):
        entities.append(callee.upper())

    for tok in re.findall(r"\b([A-Z][A-Z0-9_-]{3,})\b", code):
        if tok not in ("PIC", "VALUE", "MOVE", "PERFORM", "USING", "SECTION", "DIVISION"):
            entities.append(tok)
        if len(entities) > 20:
            break

    # 去重保序
    seen, uniq = set(), []
    for e in entities:
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)

    q_parts = uniq[:8]
    if hint.strip() and hint.strip() not in q_parts:
        q_parts.insert(0, hint.strip())
    query = " ".join(q_parts) if q_parts else code[:200]
    return query, uniq[:12]


def _evidences_to_sources(evidences: list[dict]) -> list[dict]:
    sources = []
    for i, e in enumerate(evidences[:12], start=1):
        sources.append({
            "no": i,
            "type": e.get("channel", "doc"),
            "path": e.get("obj") or e.get("label") or e.get("ref") or "",
            "label": e.get("label") or e.get("ref") or f"证据{i}",
            "snippet": (e.get("text") or "")[:220],
            "score": e.get("rank_score") or e.get("score") or 0,
            "loc": e.get("loc") or "",
            "ref": e.get("ref") or "",
        })
    return sources


def _comment_prefix(language: str) -> str:
    lang = (language or "cobol").lower()
    if lang in ("cobol", "cbl", "cob"):
        return "*"
    if lang in ("python", "py", "shell", "sh", "bash", "yaml", "yml"):
        return "#"
    return "//"


def _mock_annotate(code: str, language: str, evidences: list[dict], entities: list[str]) -> dict:
    """Mock：在段名/文件头插入证据摘要注释，不改逻辑。"""
    prefix = _comment_prefix(language)
    lines = code.splitlines()
    out: list[str] = []
    header = [
        f"{prefix} ---- KB 辅助注释（MockLLM）----",
        f"{prefix} 检索实体: {', '.join(entities[:8]) or '-'}",
    ]
    for i, e in enumerate(evidences[:4], start=1):
        label = e.get("label") or e.get("ref") or f"证据{i}"
        text = re.sub(r"\s+", " ", (e.get("text") or "")[:100])
        header.append(f"{prefix} [{i}] {label}: {text}")
    if not evidences:
        header.append(f"{prefix} TODO[KB]: 知识库未检索到相关证据，请人工补充注释")
    header.append(f"{prefix} --------------------------------")
    out.extend(header)

    inserted_for: set[str] = set()
    for line in lines:
        m = re.match(r"^(\s*)([0-9]{4}-[A-Z0-9-]+)\s*\.", line, re.I)
        if m and m.group(2).upper() not in inserted_for:
            sec = m.group(2).upper()
            inserted_for.add(sec)
            # 找是否有证据提到该段
            hit = next(
                (e for e in evidences
                 if sec.lower() in ((e.get("text") or "") + (e.get("ref") or "")).lower()),
                None,
            )
            if hit:
                snip = re.sub(r"\s+", " ", (hit.get("text") or "")[:80])
                out.append(f"{m.group(1)}{prefix} KB: 段 {sec} — {snip}")
            else:
                out.append(f"{m.group(1)}{prefix} TODO[KB]: 段 {sec} 用途待知识库/人工确认")
        out.append(line)

    notes = ["Mock 模式：已插入检索摘要与段级占位注释；配置真实 LLM 后将生成更贴合业务的注释"]
    if entities:
        notes.append(f"识别到符号：{', '.join(entities[:10])}")
    return {
        "annotated_code": "\n".join(out) + ("\n" if code.endswith("\n") else ""),
        "notes": notes,
        "uncovered": not evidences,
    }


def _parse_llm_json(raw: str) -> dict | None:
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def annotate_code(code: str, language: str = "cobol", hint: str = "") -> dict[str, Any]:
    """粘贴代码 → 知识库检索 → 生成带注释代码。"""
    code = code or ""
    if not code.strip():
        return {
            "annotated_code": "",
            "language": language or "cobol",
            "sources": [],
            "notes": ["代码为空"],
            "uncovered": True,
            "disclaimer": DISCLAIMER,
            "entities": [],
        }

    # 控制体量，避免超长 prompt
    code_for_model = code if len(code) <= 12_000 else code[:12_000] + "\n* ... truncated ...\n"
    query, entities = _extract_symbols(code_for_model, hint)
    evidences = retrieve(query, intent="how", entities=entities, top_k=6)
    sources = _evidences_to_sources(evidences)

    llm = get_llm()
    is_mock = type(llm).__name__ == "MockLLM"

    if is_mock:
        result = _mock_annotate(code_for_model, language, evidences, entities)
    else:
        ev_payload = [
            {"no": i + 1, "label": e.get("label") or e.get("ref"),
             "text": (e.get("text") or "")[:500]}
            for i, e in enumerate(evidences[:10])
        ]
        user_payload = {
            "language": language or "cobol",
            "hint": hint or "",
            "entities": entities,
            "evidence": ev_payload,
            "code": code_for_model,
        }
        try:
            raw = llm.chat(
                [
                    {"role": "system", "content": _ANNOTATE_SYSTEM},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0.2,
                json_mode=True,
            )
            parsed = _parse_llm_json(raw)
            if not parsed or not str(parsed.get("annotated_code") or "").strip():
                result = _mock_annotate(code_for_model, language, evidences, entities)
                result["notes"] = ["LLM 输出无效，已回退 Mock 注释"] + result.get("notes", [])
            else:
                result = {
                    "annotated_code": str(parsed.get("annotated_code")),
                    "notes": [str(n) for n in (parsed.get("notes") or [])][:12],
                    "uncovered": bool(parsed.get("uncovered", False)),
                }
        except Exception as exc:
            result = _mock_annotate(code_for_model, language, evidences, entities)
            result["notes"] = [f"LLM 调用失败已回退 Mock：{exc}"] + result.get("notes", [])

    return {
        "annotated_code": result.get("annotated_code") or code_for_model,
        "language": language or "cobol",
        "sources": sources,
        "notes": result.get("notes") or [],
        "uncovered": bool(result.get("uncovered", not sources)),
        "disclaimer": DISCLAIMER,
        "entities": entities,
        "query": query,
    }
