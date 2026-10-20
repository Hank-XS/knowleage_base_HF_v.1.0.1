"""MCP 知识接入工具链冒烟。"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("KB_LLM_API_KEY", "")
_repo = Path(__file__).resolve().parents[2]
if (_repo / "hf_data").exists():
    os.environ["KB_DATASET_ROOT"] = str(_repo / "hf_data")

from app.db import init_db  # noqa: E402

init_db()


def test_scan_and_clean_tools():
    from app.tools.handlers import invoke_tool

    scan = invoke_tool("scan_dataset", {})
    assert scan.get("ok") is True
    assert scan.get("total_files", 0) > 0

    # clean 较重，只断言工具可调用且产物字段齐全（若已有产物也可）
    clean = invoke_tool("clean_dataset", {})
    assert clean.get("ok") is True
    assert clean.get("kg_triples", 0) >= 50
    assert clean.get("next") == "build_knowledge_graph"
