"""知识接入 MCP 工具：上传 → 清洗 → 建图谱/向量。

推荐调用链路（Agent / Host 自动调度）：
  1) scan_dataset        盘点数据源
  2) clean_dataset       清洗产出 08_cleaned（三元组/chunk/隔离/冲突）
  3) build_knowledge_graph  三元组入图谱 + chunk 入向量
  4) kb_stats            验收规模
可选：
  upload_knowledge       单文件上传并走六步接入流水线
  ingest_knowledge_base  一键编排上述 1→4
"""
from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path
from typing import Any

from ..db import IngestJob, KbVersion, SessionLocal
from ..ingest.clean import (
    default_dataset_root,
    import_cleaned_to_stores,
    load_manifest,
    run_dataset_clean,
)
from ..ingest.pipeline import (
    _spawn_clean_govern_tasks,
    create_job,
    run_job,
)
from ..stores.graph import graph_store
from ..stores.objects import object_store
from ..stores.vector import vector_store


def tool_scan_dataset(root: str = "") -> dict:
    """扫描数据集目录，返回分层文件统计（不改写任何数据）。"""
    base = Path(root) if root.strip() else default_dataset_root()
    if not base.exists():
        return {"tool": "scan_dataset", "ok": False, "error": f"目录不存在：{base}"}

    tiers = {"A": 0, "B": 0, "C": 0, "other": 0}
    by_ext: dict[str, int] = {}
    samples: list[str] = []
    total = 0
    for p in base.rglob("*"):
        if not p.is_file() or "08_cleaned" in p.parts or ".git" in p.parts:
            continue
        total += 1
        rel = str(p.relative_to(base)).replace("\\", "/")
        ext = p.suffix.lower() or "(none)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
        if rel.startswith("02_code_assets/github_cobol"):
            tiers["A"] += 1
        elif rel.startswith("07_derived") or rel.startswith("04_system_metadata"):
            tiers["B"] += 1
        elif rel.startswith(("01_tech_docs", "02_code_assets", "03_business_rules")):
            tiers["C"] += 1
        else:
            tiers["other"] += 1
        if len(samples) < 12:
            samples.append(rel)

    return {
        "tool": "scan_dataset",
        "ok": True,
        "root": str(base),
        "total_files": total,
        "tiers": tiers,
        "by_ext": dict(sorted(by_ext.items(), key=lambda x: -x[1])[:20]),
        "samples": samples,
        "next": "clean_dataset",
    }


def tool_clean_dataset(root: str = "", out_dir: str = "") -> dict:
    """执行数据集清洗（L0—L4），产出 kg_triples / vector_chunks / quarantine / conflict_ledger。"""
    base = Path(root) if root.strip() else default_dataset_root()
    out = Path(out_dir) if out_dir.strip() else (base / "08_cleaned")
    try:
        result = run_dataset_clean(root=base, out_dir=out)
        tasks = _spawn_clean_govern_tasks(out)
    except Exception as e:
        return {"tool": "clean_dataset", "ok": False, "error": str(e)}
    return {
        "tool": "clean_dataset",
        "ok": True,
        "root": result.root,
        "out_dir": result.out_dir,
        "kg_triples": result.kg_triples,
        "vector_chunks": result.vector_chunks,
        "quarantine": result.quarantine,
        "conflicts": result.conflicts,
        "rule_hits": result.rule_hits,
        "stats": result.stats,
        "govern_tasks": tasks,
        "paths": result.paths,
        "next": "build_knowledge_graph",
    }


def tool_build_knowledge_graph(
    out_dir: str = "",
    include_tier_c: bool = True,
    min_trust: float = 0.0,
) -> dict:
    """将清洗产物导入知识图谱 + 向量库（默认含 CPS tier C）。"""
    base = default_dataset_root()
    cleaned = Path(out_dir) if out_dir.strip() else (base / "08_cleaned")
    if not (cleaned / "kg_triples.jsonl").exists():
        return {
            "tool": "build_knowledge_graph",
            "ok": False,
            "error": f"缺少清洗产物，请先 clean_dataset：{cleaned}",
            "next": "clean_dataset",
        }
    try:
        imported = import_cleaned_to_stores(
            out_dir=cleaned,
            include_tier_c=include_tier_c,
            min_trust=min_trust,
        )
        version_no = "v" + dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-kg"
        with SessionLocal() as db:
            db.add(KbVersion(
                version_no=version_no,
                change_note=(
                    f"MCP build_knowledge_graph：nodes={imported['nodes']} "
                    f"edges={imported['edges']} chunks={imported['chunks']}"
                ),
                changed_objs=[],
            ))
            job = IngestJob(
                source_type="mcp_build_graph",
                object_keys=[str(cleaned)],
                options_json={"include_tier_c": include_tier_c, "min_trust": min_trust},
                steps=[
                    {"step": "parse", "status": "done", "detail": "清洗产物已就绪"},
                    {"step": "clean", "status": "done", "detail": "跳过（已清洗）"},
                    {"step": "tag", "status": "done", "detail": "治理任务见 clean_dataset"},
                    {"step": "review", "status": "done", "detail": "MCP 工具链导入"},
                    {"step": "merge", "status": "done",
                     "detail": f"图谱 nodes={imported['nodes']} edges={imported['edges']}"},
                    {"step": "index", "status": "done",
                     "detail": f"向量 chunks={imported['chunks']}"},
                ],
                status="done",
            )
            db.add(job)
            db.commit()
            job_id = job.id
    except Exception as e:
        return {"tool": "build_knowledge_graph", "ok": False, "error": str(e)}

    g = graph_store.stats()
    return {
        "tool": "build_knowledge_graph",
        "ok": True,
        "job_id": job_id,
        "kb_version": version_no,
        "imported": imported,
        "graph": g,
        "vector": {
            "kb_doc_chunk": vector_store.count("kb_doc_chunk"),
            "kb_code_chunk": vector_store.count("kb_code_chunk"),
            "kb_mapping_chunk": vector_store.count("kb_mapping_chunk"),
        },
        "next": "kb_stats",
    }


def tool_upload_knowledge(
    filename: str,
    content_base64: str,
    source_type: str = "doc",
) -> dict:
    """单文件上传到对象库并执行六步接入（parse→clean→tag→review→merge→index）。"""
    allowed = {"error_code_table", "mapping", "message_format", "doc", "cobol"}
    if source_type not in allowed:
        return {"tool": "upload_knowledge", "ok": False,
                "error": f"source_type 必须是 {sorted(allowed)}"}
    try:
        raw = base64.b64decode(content_base64)
    except Exception as e:
        return {"tool": "upload_knowledge", "ok": False, "error": f"base64 解码失败：{e}"}
    if not raw:
        return {"tool": "upload_knowledge", "ok": False, "error": "文件内容为空"}
    try:
        key = object_store.inbox(source_type, filename or "upload.bin")
        object_store.put(key, raw)
        job_id = create_job(source_type, [key], {"filename": filename, "via": "mcp"})
        run_job(job_id)
    except Exception as e:
        return {"tool": "upload_knowledge", "ok": False, "error": str(e)[:400]}

    with SessionLocal() as db:
        job = db.get(IngestJob, job_id)
        payload = {
            "job_id": job_id,
            "status": job.status if job else "unknown",
            "steps": job.steps if job else [],
            "error": job.error if job else "",
            "object_key": key,
        }
    return {
        "tool": "upload_knowledge",
        "ok": payload["status"] == "done",
        **payload,
        "next": "kb_stats",
    }


def tool_ingest_knowledge_base(
    root: str = "",
    include_tier_c: bool = True,
    min_trust: float = 0.0,
) -> dict:
    """一键编排：scan → clean → build_knowledge_graph → stats（MCP 工具链路）。"""
    trace: list[dict[str, Any]] = []

    scan = tool_scan_dataset(root=root)
    trace.append({"step": 1, "tool": "scan_dataset",
                  "result": f"files={scan.get('total_files')} ok={scan.get('ok')}"})
    if not scan.get("ok"):
        return {"tool": "ingest_knowledge_base", "ok": False, "trace": trace, "scan": scan}

    clean = tool_clean_dataset(root=root)
    trace.append({"step": 2, "tool": "clean_dataset",
                  "result": (f"triples={clean.get('kg_triples')} chunks={clean.get('vector_chunks')} "
                             f"quar={clean.get('quarantine')}")})
    if not clean.get("ok"):
        return {"tool": "ingest_knowledge_base", "ok": False, "trace": trace, "clean": clean}

    build = tool_build_knowledge_graph(
        out_dir=clean.get("out_dir", ""),
        include_tier_c=include_tier_c,
        min_trust=min_trust,
    )
    trace.append({"step": 3, "tool": "build_knowledge_graph",
                  "result": f"imported={build.get('imported')} ok={build.get('ok')}"})
    if not build.get("ok"):
        return {"tool": "ingest_knowledge_base", "ok": False, "trace": trace,
                "clean": clean, "build": build}

    from .handlers import tool_kb_stats
    stats = tool_kb_stats()
    trace.append({"step": 4, "tool": "kb_stats",
                  "result": f"nodes={stats.get('graph', {}).get('nodes')} "
                            f"edges={stats.get('graph', {}).get('edges')}"})

    mf = load_manifest(Path(clean["out_dir"])) if clean.get("out_dir") else {}
    return {
        "tool": "ingest_knowledge_base",
        "ok": True,
        "trace": trace,
        "scan": {k: scan[k] for k in ("root", "total_files", "tiers") if k in scan},
        "clean": {k: clean[k] for k in (
            "kg_triples", "vector_chunks", "quarantine", "conflicts", "out_dir") if k in clean},
        "build": {k: build[k] for k in (
            "job_id", "kb_version", "imported", "graph", "vector") if k in build},
        "stats": stats,
        "manifest_notes": (mf or {}).get("notes", [])[:4],
    }


INGEST_TOOL_HANDLERS = {
    "scan_dataset": tool_scan_dataset,
    "clean_dataset": tool_clean_dataset,
    "build_knowledge_graph": tool_build_knowledge_graph,
    "upload_knowledge": tool_upload_knowledge,
    "ingest_knowledge_base": tool_ingest_knowledge_base,
}

INGEST_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "scan_dataset",
        "description": "扫描知识数据源目录（默认 hf_data），返回文件分层统计。接入前第一步。",
        "parameters": {
            "type": "object",
            "properties": {"root": {"type": "string", "default": "",
                                    "description": "数据集根目录，空则用 KB_DATASET_ROOT/hf_data"}},
        },
    },
    {
        "name": "clean_dataset",
        "description": "清洗数据集：隔离危险内容、抽三元组与 chunk，写入 08_cleaned。"
                       "生成知识图谱前必须先调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": ""},
                "out_dir": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "build_knowledge_graph",
        "description": "将清洗产物导入知识图谱与向量库（生成/更新图谱）。"
                       "依赖 clean_dataset 产出的 kg_triples.jsonl / vector_chunks.jsonl。",
        "parameters": {
            "type": "object",
            "properties": {
                "out_dir": {"type": "string", "default": ""},
                "include_tier_c": {"type": "boolean", "default": False},
                "min_trust": {"type": "number", "default": 0.0},
            },
        },
    },
    {
        "name": "upload_knowledge",
        "description": "上传单个知识文件（base64）并执行六步接入流水线。"
                       "source_type: error_code_table|mapping|message_format|doc|cobol。",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "content_base64": {"type": "string"},
                "source_type": {"type": "string", "default": "doc"},
            },
            "required": ["filename", "content_base64"],
        },
    },
    {
        "name": "ingest_knowledge_base",
        "description": "一键知识库接入编排：scan_dataset → clean_dataset → "
                       "build_knowledge_graph → kb_stats。适合批量上传 hf_data。",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": ""},
                "include_tier_c": {"type": "boolean", "default": False},
                "min_trust": {"type": "number", "default": 0.0},
            },
        },
    },
]
