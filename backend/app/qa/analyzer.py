"""问题分析器：意图分类 / 实体抽取 / 查询改写（设计 5.2 节）。"""
from __future__ import annotations

import re

from ..stores.graph import graph_store

INTENTS = ("code_understanding", "business_rule", "impact_analysis", "data_processing")
INTENT_LABELS = {
    "code_understanding": "代码理解",
    "business_rule": "业务规则",
    "impact_analysis": "影响分析",
    "data_processing": "数据处理",
}

_IMPACT_KW = ("影响", "波及", "改动", "修改", "变更", "动到")
_CODE_KW = ("程序", "代码", "段落", "section", "perform", "cobol", "逻辑", "注释")
_RULE_KW = ("规则", "错误码", "报错", "余额不足", "校验", "限额", "怎么处理", "排查", "为什么")


def classify_intent(question: str) -> str:
    q = question.lower()
    if any(k in q for k in _IMPACT_KW) and any(k in q for k in ("影响", "波及")):
        return "impact_analysis"
    if any(k in q for k in _CODE_KW):
        return "code_understanding"
    if any(k in q for k in _RULE_KW):
        return "business_rule"
    return "data_processing"


def extract_entities(question: str, history: list[dict] | None = None) -> list[str]:
    """词典匹配（图谱实体名 + 错误码 + 卡种）＋历史实体继承。"""
    ents: set[str] = set()
    q = question.lower()
    for n in graph_store.dump()["nodes"]:
        name = str(n["props"].get("name", ""))
        if not name or len(name) < 2:
            continue
        nl = name.lower()
        if nl in q:
            ents.add(n["props"].get("name"))
        elif n["label"] == "ErrorCode" and n["props"].get("code") and n["props"]["code"] in q:
            ents.add(name)
    # 错误码数字形式：错误码 14 / code 14
    for m in re.findall(r"(?:错误码|error\s?code)\s*[:：]?\s*(\d{1,4})", q):
        for n in graph_store.find("ErrorCode", code=m):
            ents.add(n["props"]["name"])
    # 历史继承（追问省略主语）
    for h in (history or [])[-2:]:
        for e in h.get("entities", []):
            if any(k in q for k in ("呢", "区别", "它", "该", "上述", "还是")) or len(q) < 18:
                ents.add(e)
    return sorted(ents)[:8]


def rewrite_query(question: str, entities: list[str], history: list[dict] | None = None) -> str:
    parts = [question.strip()]
    if entities:
        parts.append("（相关实体：" + "、".join(entities) + "）")
    if history:
        last_q = history[-1].get("question", "")
        if last_q:
            parts.append(f"（承接上文问题：{last_q[:60]}）")
    return " ".join(parts)
