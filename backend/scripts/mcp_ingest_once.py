"""按 MCP 工具调用链路执行一次知识库上传 + 图谱构建。

链路：
  scan_dataset → clean_dataset → build_knowledge_graph → kb_stats

用法：
  cd backend
  python scripts/mcp_ingest_once.py
  python scripts/mcp_ingest_once.py --tier-c   # 含 tier C
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="", help="数据集根，默认 hf_data")
    ap.add_argument("--tier-c", action="store_true", help="导入时包含 tier C")
    ap.add_argument("--one-shot", action="store_true",
                    help="直接调用 ingest_knowledge_base（默认分步调用）")
    args = ap.parse_args()

    from app.db import init_db
    from app.ingest.tagger import ensure_vocab
    from app.seed import seed_users
    from app.tools.handlers import invoke_tool

    init_db()
    seed_users()
    ensure_vocab()

    print("=== MCP 工具链路：知识接入 + 图谱构建 ===\n")

    if args.one_shot:
        result = invoke_tool("ingest_knowledge_base", {
            "root": args.root,
            "include_tier_c": args.tier_c,
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    # 分步：模拟 Host / Agent 逐个调度 MCP tools
    chain = [
        ("scan_dataset", {"root": args.root}),
        ("clean_dataset", {"root": args.root}),
        ("build_knowledge_graph", {
            "include_tier_c": args.tier_c,
            "min_trust": 0.0,
        }),
        ("kb_stats", {}),
    ]
    final = {}
    for i, (name, params) in enumerate(chain, 1):
        # build 时带上 clean 的 out_dir
        if name == "build_knowledge_graph" and final.get("out_dir"):
            params = {**params, "out_dir": final["out_dir"]}
        print(f"[{i}/{len(chain)}] invoke_tool({name!r}, {params})")
        result = invoke_tool(name, params)
        ok = result.get("ok", True) if "ok" in result else "error" not in result
        print(f"  → ok={ok} summary={_brief(result)}\n")
        if not ok:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        if name == "clean_dataset":
            final["out_dir"] = result.get("out_dir")
        final[name] = result

    print("=== 完成 ===")
    print(json.dumps({
        "scan": final.get("scan_dataset", {}).get("total_files"),
        "clean": {
            "kg_triples": final.get("clean_dataset", {}).get("kg_triples"),
            "vector_chunks": final.get("clean_dataset", {}).get("vector_chunks"),
            "quarantine": final.get("clean_dataset", {}).get("quarantine"),
        },
        "graph": final.get("build_knowledge_graph", {}).get("imported"),
        "stats": final.get("kb_stats"),
    }, ensure_ascii=False, indent=2))
    return 0


def _brief(r: dict) -> str:
    if r.get("error"):
        return f"error:{r['error']}"[:120]
    if "total_files" in r:
        return f"files={r['total_files']} tiers={r.get('tiers')}"
    if "kg_triples" in r:
        return (f"triples={r['kg_triples']} chunks={r['vector_chunks']} "
                f"quar={r['quarantine']} conflicts={r.get('conflicts')}")
    if "imported" in r:
        return f"imported={r['imported']} version={r.get('kb_version')}"
    if "graph" in r:
        g = r["graph"]
        return f"nodes={g.get('nodes')} edges={g.get('edges')}"
    return "ok"


if __name__ == "__main__":
    raise SystemExit(main())
