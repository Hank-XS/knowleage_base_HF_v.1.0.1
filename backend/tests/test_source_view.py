"""依据文档预览解析。"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("KB_LLM_API_KEY", "")
_repo = Path(__file__).resolve().parents[2]
if (_repo / "hf_data").exists():
    os.environ["KB_DATASET_ROOT"] = str(_repo / "hf_data")

from app.db import init_db  # noqa: E402

init_db()


def test_preview_seed_or_dataset_doc():
    from app.qa.source_view import preview_source
    from app.seed import seed_knowledge

    seed_knowledge(force=False)
    # seed 文档经 inbox 入库；用文件名回落匹配
    doc = preview_source(
        path="atm_withdraw_flow.md",
        source_type="doc",
        ref="ATM取款",
        snippet="取款",
    )
    assert doc["available"] or doc["content"]
    assert "取款" in doc["content"] or doc["from_cache"]


def test_preview_graph_entity():
    from app.qa.source_view import preview_source
    from app.seed import seed_knowledge

    seed_knowledge(force=False)
    doc = preview_source(source_type="graph", ref="错误码14", snippet="余额不足")
    assert doc["type"] == "graph"
    assert doc["content"]
