"""离线接入流水线：parse → clean → tag → review → merge → index。

- clean：L1—L4 规范化/隔离预检（单文件）或数据集全量清洗；
- tag 步骤生成治理任务（AI/规则标签待人工校对）；
- merge 步骤写图谱并生成 kb_version，触发已验证答案失效联动；
- index 步骤写向量库（三集合）。
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from ..db import GovernTask, IngestJob, KbVersion, SessionLocal
from ..knowledge.cache import invalidate_by_objects
from ..llm import get_embedder, get_llm
from ..stores.graph import graph_store
from ..stores.objects import object_store
from ..stores.vector import vector_store
from .clean import clean_content_preview, import_cleaned_to_stores, load_jsonl, run_dataset_clean
from .parsers import ParsedBundle, parse_by_type

STEPS = ["parse", "clean", "tag", "review", "merge", "index"]


def _steps_init() -> list[dict]:
    return [{"step": s, "status": "pending", "detail": ""} for s in STEPS]


def _llm_tags(bundle_nodes: list[tuple]) -> list[dict]:
    """占位保留：旧版直连打标已由 tagger.cross_tag_units 取代（代码×文档证据融合）。"""
    return []


def _spawn_clean_govern_tasks(out_dir: Path) -> dict:
    """清洗后：隔离复审 + 冲突裁决 → 治理任务。"""
    quar = load_jsonl(out_dir / "quarantine.jsonl", limit=200)
    conflicts = load_jsonl(out_dir / "conflict_ledger.jsonl", limit=200)
    created = {"quarantine_task": None, "conflict_task": None}
    with SessionLocal() as db:
        if quar:
            items = [{
                "item_id": f"q_{i+1:04d}",
                "node_id": q.get("path", ""),
                "tag": {"category": "治理", "value": q.get("role", "quarantine")},
                "source": "clean",
                "status": "pending",
                "reason": f"{q.get('rule', '')}: {q.get('reason', '')}",
                "preview": q.get("preview", "")[:160],
            } for i, q in enumerate(quar)]
            task = GovernTask(
                task_type="quarantine_review",
                title=f"[清洗] 隔离区复审（{len(items)} 项）",
                items_json=items, status="pending")
            db.add(task)
            db.flush()
            created["quarantine_task"] = task.id
        if conflicts:
            items = [{
                "item_id": f"c_{i+1:04d}",
                "node_id": c.get("conflict_id", ""),
                "tag": {"category": "治理", "value": "conflict"},
                "source": "clean",
                "status": "pending",
                "reason": f"{c.get('rule', '')}: {c.get('subject', '')}",
                "suggestion": c.get("suggestion", ""),
            } for i, c in enumerate(conflicts)]
            task = GovernTask(
                task_type="conflict_review",
                title=f"[清洗] 冲突台账裁决（{len(items)} 项）",
                items_json=items, status="pending")
            db.add(task)
            db.flush()
            created["conflict_task"] = task.id
        db.commit()
    return created


def run_dataset_clean_job(do_import: bool = False, include_tier_c: bool = False) -> dict:
    """全量数据集清洗（可记为 IngestJob），可选导入图谱/向量。"""
    with SessionLocal() as db:
        job = IngestJob(source_type="dataset_clean", object_keys=["hf_data"],
                        options_json={"do_import": do_import, "include_tier_c": include_tier_c},
                        steps=_steps_init(), status="running")
        db.add(job)
        db.commit()
        job_id = job.id

        def _set(step: str, status: str, detail: str = "") -> None:
            for s in job.steps:
                if s["step"] == step:
                    s.update(status=status, detail=detail)
            flag_modified(job, "steps")
            db.commit()

        try:
            _set("parse", "done", "数据集目录扫描（L0 只读）")
            result = run_dataset_clean()
            _set("clean", "done",
                 f"三元组 {result.kg_triples} / chunk {result.vector_chunks} / "
                 f"隔离 {result.quarantine} / 冲突 {result.conflicts}")
            tasks = _spawn_clean_govern_tasks(Path(result.out_dir))
            _set("tag", "done",
                 f"治理任务：隔离复审={tasks.get('quarantine_task') or '-'}，"
                 f"冲突裁决={tasks.get('conflict_task') or '-'}")
            _set("review", "done", "隔离/冲突待治理工作台人工校对")

            imported = None
            if do_import:
                imported = import_cleaned_to_stores(include_tier_c=include_tier_c)
                version_no = "v" + dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-clean"
                ver = KbVersion(version_no=version_no,
                                change_note=f"数据集清洗导入：edges={imported['edges']} chunks={imported['chunks']}",
                                changed_objs=[])
                db.add(ver)
                db.commit()
                _set("merge", "done",
                     f"图谱导入 nodes={imported['nodes']} edges={imported['edges']}，版本 {version_no}")
                _set("index", "done", f"{imported['chunks']} 个清洗 chunk 向量化入库")
            else:
                _set("merge", "done", "跳过导入（仅产出 08_cleaned；可调用 /ingest/clean/import）")
                _set("index", "done", "跳过向量化（产物已落盘，待导入）")
            job.status = "done"
            db.commit()
            return {"job_id": job_id, "clean": result.to_dict(),
                    "govern_tasks": tasks, "imported": imported}
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            for s in job.steps:
                if s["status"] == "pending":
                    s.update(status="skipped")
            flag_modified(job, "steps")
            db.commit()
            raise


def run_job(job_id: str) -> None:
    """同步执行任务（Demo 规模；推广期换 Celery worker）。"""
    with SessionLocal() as db:
        job = db.get(IngestJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.steps = _steps_init()
        flag_modified(job, "steps")
        db.commit()
        bundles: list[ParsedBundle] = []

        def _set(step: str, status: str, detail: str = "") -> None:
            for s in job.steps:
                if s["step"] == step:
                    s.update(status=status, detail=detail)
            flag_modified(job, "steps")
            db.commit()

        try:
            # 1) parse
            file_blobs: list[tuple[str, bytes, str]] = []
            for key in job.object_keys:
                from ..stores.objects import object_store as obs
                path = obs._root / key.lstrip("/")
                if not path.exists():
                    raise ValueError(f"对象不存在：{key}")
                content = path.read_bytes()
                file_blobs.append((path.name, content, key))
                bundle = parse_by_type(job.source_type, content, path.name, key)
                bundles.append(bundle)
            _set("parse", "done", f"{len(bundles)} 个文件解析成功")

            # 2) clean —— 单文件隔离预检 + 元数据 enrich
            clean_notes = []
            blocked = []
            for (fname, content, key), bundle in zip(file_blobs, bundles):
                preview = clean_content_preview(fname, content)
                if preview["quarantined"]:
                    blocked.append(f"{fname}({preview['rule']})")
                    clean_notes.append(f"隔离 {fname}: {preview['reason']}")
                else:
                    # 给 chunk 附加清洗元数据
                    for ch in bundle.chunks:
                        ch.setdefault("meta", {})
                        ch["meta"].setdefault("tier", "B")
                        ch["meta"].setdefault("trust", 0.75)
                        ch["meta"].setdefault("kind", f"ingest_{job.source_type}")
                        if preview.get("test_mode"):
                            ch["meta"]["test_mode"] = True
                            ch["meta"]["trust"] = float(ch["meta"].get("trust", 0.75)) * 0.7
                    if preview["conflicts"]:
                        clean_notes.append(f"{fname}: {len(preview['conflicts'])} 条冲突标注")
            if blocked:
                raise ValueError(f"清洗隔离拦截，禁止入库：{', '.join(blocked)}")
            _set("clean", "done",
                 "；".join(clean_notes) if clean_notes else "内容预检通过，已附加 tier/trust 元数据")

            # 3) tag（规则标签 → 治理任务；规则/清洗不校验词表，仅 AI 交叉打标校验）
            items = []
            for b in bundles:
                for t in b.tags:
                    items.append({"item_id": f"tag_{len(items)+1:04d}", "node_id": t["node_id"],
                                  "tag": t["tag"], "source": t["source"], "status": "pending"})
            if items:
                task = GovernTask(task_type="tagging",
                                  title=f"[{job.source_type}] 打标校对任务（{len(items)} 条）",
                                  items_json=items[:200], status="pending")
                db.add(task)
            xtag_note = ""
            try:
                from .tagger import cross_tag_units
                xt = cross_tag_units()
                if xt.get("skipped"):
                    xtag_note = f"；交叉打标跳过（{xt.get('reason', '')}）"
                else:
                    xtag_note = (f"；交叉打标 {xt['units']} 程序："
                                 f"自动通过 {xt['auto_applied']}，待校对 {xt['pending_items']}")
            except Exception as e:
                xtag_note = f"；交叉打标失败：{str(e)[:80]}"
            _set("tag", "done", f"{len(items)} 条规则标签进入治理队列{xtag_note}")

            # 4) review —— Demo 策略：知识先入库可查，标签状态标记未校对（人工校对兜底）
            _set("review", "done", "知识已入库；标签待治理工作台人工校对")

            # 5) merge（图谱 + 版本 + 失效联动）
            changed: list[str] = []
            for b in bundles:
                for (nid, label, props) in b.nodes:
                    graph_store.upsert_node(nid, label, props)
                    changed.append(nid)
                for (src, rel, dst, props) in b.edges:
                    graph_store.upsert_edge(src, rel, dst, props)
            graph_store.save()
            version_no = "v" + dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4]
            ver = KbVersion(version_no=version_no,
                            change_note=f"接入 {job.source_type}：{len(job.object_keys)} 个文件",
                            changed_objs=sorted(set(changed))[:500])
            db.add(ver)
            db.commit()
            stale = invalidate_by_objects(sorted(set(changed))[:500])
            _set("merge", "done", f"图谱合并完成，版本 {version_no}，{stale} 条已验证答案转 stale")

            # 6) index（向量化三集合）
            emb = get_embedder()
            n = 0
            for b in bundles:
                for ch in b.chunks:
                    vec = emb.embed([ch["text"]])[0]
                    meta = dict(ch["meta"])
                    meta["text"] = ch["text"]
                    meta["kb_version"] = version_no
                    vector_store.upsert(ch["collection"], ch["chunk_id"], vec, meta)
                    n += 1
            vector_store.save()
            _set("index", "done", f"{n} 个 chunk 向量化入库")
            job.status = "done"
            db.commit()
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            for s in job.steps:
                if s["status"] == "pending":
                    s.update(status="skipped")
            flag_modified(job, "steps")
            db.commit()
            raise


def create_job(source_type: str, object_keys: list[str], options: dict | None = None) -> str:
    with SessionLocal() as db:
        job = IngestJob(source_type=source_type, object_keys=object_keys,
                        options_json=options or {}, steps=_steps_init(), status="queued")
        db.add(job)
        db.commit()
        return job.id


def apply_tag_review(task_id: str, actions: list[dict], operator: str) -> dict:
    """治理工作台提交校对结果：accept / modify / reject。"""
    with SessionLocal() as db:
        task = db.get(GovernTask, task_id)
        if task is None:
            raise ValueError("任务不存在")
        # 复制一份再写回，并 flag_modified：SQLAlchemy 对 JSON 原地改动默认不落库
        # 规则/清洗标签入图谱不校验词表；AI 标签在 cross_tag_units 已做封闭集过滤
        items_list = [dict(it) for it in (task.items_json or [])]
        items = {it.get("item_id"): it for it in items_list if it.get("item_id")}
        applied, rejected = [], []
        for a in actions:
            it = items.get(a.get("item_id"))
            if not it:
                continue
            action = a.get("action")
            if action == "accept":
                applied.append(it)
                it["status"] = "accepted"
            elif action == "modify":
                it["tag"] = a.get("tag") or it.get("tag")
                it["status"] = "modified"
                applied.append(it)
            elif action == "reject":
                it["status"] = "rejected"
                it["reason"] = a.get("reason", "")
                rejected.append(it)
        wrote = 0
        for it in applied:
            node_id = (it.get("node_id") or "").strip()
            tag = it.get("tag") or {}
            if not node_id or not tag.get("category") or not tag.get("value"):
                continue
            tid = graph_store.upsert_node(
                f"tag/{tag['category']}:{tag['value']}", "Tag",
                {"name": f"{tag['category']}:{tag['value']}", "category": tag["category"],
                 "value": tag["value"], "source": it.get("source", "rule"), "verified": True})
            if graph_store.node(node_id) is None:
                graph_store.upsert_node(node_id, "CodeUnit", {"name": node_id})
            graph_store.upsert_edge(node_id, "TAGGED", tid,
                                    {"confidence": it.get("confidence"),
                                     "reason": it.get("reason", ""),
                                     "auto": False})
            wrote += 1
        if wrote:
            graph_store.save()
        task.items_json = items_list
        flag_modified(task, "items_json")
        task.status = "done" if all(i.get("status") != "pending" for i in items_list) else "pending"
        task.operator = operator
        db.commit()
        return {"applied": len(applied), "rejected": len(rejected), "task_status": task.status}
