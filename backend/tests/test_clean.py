"""数据集清洗：隔离规则、跨宇宙消歧、全量清洗产物、流水线 clean 步骤。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("KB_LLM_API_KEY", "")

_tmp = tempfile.mkdtemp(prefix="kbclean_")
# 指向仓库内 hf_data（若存在）
_repo_data = Path(__file__).resolve().parents[2] / "hf_data"
if _repo_data.exists():
    os.environ["KB_DATASET_ROOT"] = str(_repo_data)

import app.db as db_mod  # noqa: E402
from app.db import init_db  # noqa: E402

init_db()


def test_quarantine_and_universe():
    from app.ingest.clean import (
        clean_content_preview,
        infer_universe,
        namespaced,
        should_quarantine,
    )

    assert infer_universe("03_business_rules/SRS.md", "FR-001") == "CPS"
    assert infer_universe("07_derived/SRS-CARD.md", "FR-01") == "CARD"
    assert namespaced("FR-001", "CPS") == "CPS:FR-001"
    assert namespaced("FR-01", "CARD") == "CARD:FR-01"
    assert namespaced("CPS:PYMAIN", "CPS") == "CPS:PYMAIN"

    q = should_quarantine(Path("PYMAIN.OLD.cbl"), "PROGRAM-ID. PYMAIN.")
    assert q and q[0] == "R-Q1"

    preview = clean_content_preview(
        "evil.sh", b"export client_secret=abc123\necho ok\n")
    assert preview["quarantined"] is True
    assert preview["rule"] == "R-Q2"


def test_run_dataset_clean_and_import():
    from app.ingest.clean import (
        default_dataset_root,
        import_cleaned_to_stores,
        load_manifest,
        run_dataset_clean,
    )

    root = default_dataset_root()
    if not root.exists():
        return  # 无数据集时跳过全量用例

    out = Path(_tmp) / "08_cleaned"
    result = run_dataset_clean(root=root, out_dir=out)
    assert result.kg_triples >= 50
    assert result.vector_chunks >= 50
    assert result.quarantine >= 1
    assert (out / "manifest.json").exists()
    assert (out / "conflict_ledger.jsonl").exists()
    mf = load_manifest(out)
    assert mf.get("kg_triples") == result.kg_triples

    # 导入 A/B（不含 C）不应抛错
    import app.stores.graph as g
    import app.stores.vector as v
    g.graph_store = g.MemGraphStore()
    g.graph_store._path = Path(_tmp) / "graph.json"
    v.vector_store = v.NumpyVectorStore()
    v.vector_store._path = Path(_tmp) / "vec.json"
    # 重新绑定 clean 模块使用的全局 store
    import app.ingest.clean as clean_mod
    # import 函数内部 from ..stores.graph import graph_store —— 需 monkeypatch 模块属性
    import app.stores.graph as graph_mod
    import app.stores.vector as vector_mod
    graph_mod.graph_store = g.graph_store
    vector_mod.vector_store = v.vector_store

    stats = import_cleaned_to_stores(out_dir=out, include_tier_c=False)
    assert stats["chunks"] > 0
    assert stats["edges"] + stats["nodes"] > 0


def test_pipeline_clean_blocks_quarantine():
    from app.ingest.pipeline import create_job, run_job
    from app.stores.objects import object_store

    key = object_store.inbox("doc", "VIP_skip_aml_note.md")
    object_store.put(key, b"# note\nVIP skip AML for whitelist customers\n")
    job_id = create_job("doc", [key], {"filename": "VIP_skip_aml_note.md"})
    try:
        run_job(job_id)
        assert False, "应被清洗隔离拦截"
    except ValueError as e:
        assert "隔离" in str(e)

    with db_mod.SessionLocal() as db:
        job = db.get(db_mod.IngestJob, job_id)
        assert job is not None
        assert job.status == "failed"
        steps = {s["step"]: s["status"] for s in job.steps}
        assert steps.get("parse") == "done"
        assert "clean" in steps
