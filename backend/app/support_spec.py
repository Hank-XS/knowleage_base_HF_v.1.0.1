"""生成式样书：先走代码注释，再用配置的式样书提示词增强为 Markdown。"""
from __future__ import annotations

import json
import re
from typing import Any

from .llm import get_llm
from .prompt_config import TYPE_TITLES, get_prompt
from .response import KbError
from .support_annotate import annotate_code

DISCLAIMER = "式样书在「注释结果」基础上经配置提示词增强生成，需人工复核后合入。"


def infer_prompt_type(path: str = "", language: str = "", kind: str = "") -> str:
    p = (path or "").replace("\\", "/").lower()
    lang = (language or "").lower()
    k = (kind or "").lower()
    if "copybook" in p or lang == "copybook" or p.endswith(".cpy") or k == "copybook":
        return "copybook"
    if lang == "jcl" or p.endswith(".jcl") or "/jcl/" in p or k in ("step", "batch"):
        return "batch"
    if "interface" in p or "/interfaces/" in p:
        return "interface"
    return "program"


def _mock_spec_from_annotate(
    title: str,
    prompt_type: str,
    path: str,
    annotated: dict[str, Any],
) -> str:
    code = annotated.get("annotated_code") or ""
    entities = annotated.get("entities") or []
    sources = annotated.get("sources") or []
    notes = annotated.get("notes") or []
    paras = re.findall(r"^\s*([0-9]{3,4}-[A-Z0-9-]+)\s*\.", code, re.M | re.I)
    calls = re.findall(r"\bCALL\s+'([A-Z0-9_-]+)'", code, re.I)
    copies = re.findall(r"\bCOPY\s+([A-Z0-9_-]+)", code, re.I)

    lines = [
        f"# {title}",
        "",
        f"> 类型：{TYPE_TITLES.get(prompt_type, prompt_type)}　路径：`{path or '-'}`",
        "> 流水线：源码 → 知识库注释 → 式样书提示词增强（Mock）",
        "",
        "## 1. 概述",
        f"- 对象标识：{', '.join(entities[:8]) or '待确认'}",
        f"- 注释后源码行数：{len(code.splitlines())}",
        "",
        "## 2. 输入输出",
        "- 待确认：请结合注释中的 CALL/COPY/数据区说明补充。",
        "",
        "## 3. 处理逻辑",
        "以下逻辑摘自注释增强后的代码要点：",
    ]
    # 抽取 * 注释中的 KB / TODO 行作为逻辑要点
    kb_notes = [
        ln.strip().lstrip("*").strip()
        for ln in code.splitlines()
        if ln.strip().startswith("*") and ("KB" in ln.upper() or "TODO" in ln.upper())
    ][:16]
    if kb_notes:
        for n in kb_notes:
            lines.append(f"- {n}")
    elif paras:
        lines.append("- 主要段：")
        for p in paras[:20]:
            lines.append(f"  - `{p.upper()}`")
    else:
        lines.append("- 待确认：请人工补充处理步骤。")

    if calls:
        uniq = list(dict.fromkeys(c.upper() for c in calls))
        lines.append("- CALL：" + ", ".join(f"`{c}`" for c in uniq[:12]))
    if copies:
        uniq = list(dict.fromkeys(c.upper() for c in copies))
        lines.append("- COPY：" + ", ".join(f"`{c}`" for c in uniq[:12]))

    lines += ["", "## 4. 异常与返回码", "- 待确认：对照错误码与注释中的异常说明。", ""]
    if notes:
        lines.append("### 注释阶段说明")
        for n in notes[:8]:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("## 5. 依据与备注")
    if sources:
        for s in sources[:10]:
            no = s.get("no", "")
            label = s.get("label") or s.get("path") or f"证据{no}"
            snip = re.sub(r"\s+", " ", (s.get("snippet") or "")[:120])
            lines.append(f"- [{no}] {label}：{snip}")
    else:
        lines.append("- 知识库未检索到相关证据，请人工补充。")
    lines += ["", f"*{DISCLAIMER}*"]
    return "\n".join(lines)


def generate_spec(
    code: str,
    *,
    prompt_type: str = "program",
    path: str = "",
    language: str = "",
    hint: str = "",
    annotated_code: str = "",
    annotate_payload: dict | None = None,
) -> dict[str, Any]:
    """注释结果 + 配置提示词 → Markdown 式样书。

    若传入 annotated_code（前端已生成注释），则不再重复跑注释；
    否则回退为先 annotate_code 再增强。
    """
    code = code or ""
    pre_ann = (annotated_code or "").strip()
    if not pre_ann and not code.strip():
        raise KbError("40001", "请先生成注释，或提供源码")

    ptype = (prompt_type or infer_prompt_type(path, language)).strip().lower()
    tpl = get_prompt(ptype)
    if not tpl.get("enabled"):
        raise KbError("40001", f"提示词类型 {ptype} 已停用，请先在「式样书提示词」中启用")

    system_prompt = (tpl.get("system_prompt") or "").strip()
    if not system_prompt:
        raise KbError("40001", "system_prompt 为空")

    # 1) 使用已有注释，或回退生成注释
    if pre_ann:
        annotated = {
            "annotated_code": pre_ann,
            "sources": (annotate_payload or {}).get("sources") or [],
            "entities": (annotate_payload or {}).get("entities") or [],
            "notes": (annotate_payload or {}).get("notes") or [],
            "uncovered": (annotate_payload or {}).get("uncovered"),
            "disclaimer": (annotate_payload or {}).get("disclaimer"),
            "query": (annotate_payload or {}).get("query"),
        }
        notes = ["基于已生成的注释结果增强式样书"]
    else:
        annotated = annotate_code(code, language=language or "cobol", hint=hint or path)
        notes = ["已先完成知识库辅助注释"]
    annotated_code_out = annotated.get("annotated_code") or code or pre_ann
    sources = annotated.get("sources") or []
    entities = annotated.get("entities") or []
    title = tpl.get("title") or TYPE_TITLES.get(ptype, ptype)
    notes.extend(f"[注释] {n}" for n in (annotated.get("notes") or [])[:6])

    # 控制入模体量
    ann_for_model = (
        annotated_code_out if len(annotated_code_out) <= 12_000
        else annotated_code_out[:12_000] + "\n* ... truncated ...\n"
    )

    llm = get_llm()
    is_mock = type(llm).__name__ == "MockLLM"

    # 2) 用配置提示词在「注释结果」上增强为式样书
    if is_mock:
        markdown = _mock_spec_from_annotate(title, ptype, path, annotated)
        notes.append("Mock 模式：已在注释结果上生成骨架式样书")
    else:
        ev_payload = [
            {
                "no": s.get("no"),
                "label": s.get("label") or s.get("path"),
                "text": (s.get("snippet") or "")[:400],
            }
            for s in sources[:12]
        ]
        user_payload = {
            "prompt_type": ptype,
            "title": title,
            "path": path,
            "language": language,
            "hint": hint,
            "entities": entities,
            "evidence": ev_payload,
            "annotate_notes": (annotated.get("notes") or [])[:8],
            "annotated_code": ann_for_model,
        }
        enhance_system = (
            system_prompt
            + "\n\n[增强约束]\n"
            "你拿到的是「已插入知识库注释的代码」与证据。"
            "请在注释要点之上撰写式样书，不得与注释中的事实冲突；"
            "证据不足处写「待确认」；输出纯 Markdown，不要包 JSON。"
        )
        try:
            raw = llm.chat(
                [
                    {"role": "system", "content": enhance_system},
                    {"role": "user", "content": (
                        "请基于下列「注释后代码」与证据，按提示词要求增强为完整式样书。\n"
                        + json.dumps(user_payload, ensure_ascii=False)
                    )},
                ],
                temperature=0.2,
                json_mode=False,
            )
            markdown = (raw or "").strip()
            if not markdown or markdown.startswith("【MockLLM】"):
                markdown = _mock_spec_from_annotate(title, ptype, path, annotated)
                notes.append("LLM 输出无效，已回退骨架式样书")
            else:
                notes.append(f"已用配置提示词「{title}」在注释基础上增强")
        except Exception as exc:
            markdown = _mock_spec_from_annotate(title, ptype, path, annotated)
            notes.append(f"LLM 增强失败已回退骨架：{exc}")

    return {
        "prompt_type": ptype,
        "title": title,
        "markdown": markdown,
        "annotated_code": annotated_code_out,
        "annotate": {
            "notes": annotated.get("notes") or [],
            "uncovered": bool(annotated.get("uncovered")),
            "disclaimer": annotated.get("disclaimer"),
        },
        "path": path,
        "language": language or "",
        "sources": sources,
        "notes": notes,
        "uncovered": bool(annotated.get("uncovered", not sources)),
        "disclaimer": DISCLAIMER,
        "entities": entities,
        "query": annotated.get("query"),
        "prompt_updated_at": tpl.get("updated_at"),
    }
