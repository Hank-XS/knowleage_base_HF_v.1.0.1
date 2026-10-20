"""数据指纹与三级分流（设计 5.3 节 / 附录 B 参考实现）。"""
from __future__ import annotations

import hashlib
import re

from ..config import settings

SYNONYMS = {
    "提款": "取款", "取钱": "取款", " atm ": " atm ", "报错": "错误", "报文": "报文",
    "怎么处理": "怎么处理", "如何处理": "怎么处理", "怎么办": "怎么处理",
    "排查": "排查", "检查": "排查", "处理": "处理",
}


def normalize_question(question: str, scene_code: str, entities: list[str]) -> str:
    norm = question.strip().lower()
    norm = re.sub(r"\s+", "", norm)
    norm = re.sub(r"[？?！!。，,；;：:\"'（）()\[\]【】]", "", norm)
    for k, v in SYNONYMS.items():
        norm = norm.replace(k.strip(), v)
    ents = ",".join(sorted({e.lower() for e in entities}))
    return f"{scene_code}|{ents}|{norm}"


def compute_fingerprint(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def route_by_similarity(sim: float,
                        exact: float | None = None,
                        similar: float | None = None) -> str:
    th_e = exact if exact is not None else settings.threshold_exact
    th_s = similar if similar is not None else settings.threshold_similar
    if sim >= th_e:
        return "exact"
    if sim >= th_s:
        return "similar"
    return "miss"
