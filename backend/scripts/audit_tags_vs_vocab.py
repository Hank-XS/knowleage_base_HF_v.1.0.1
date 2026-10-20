"""核对图谱 Tag / TAGGED 是否落在受控词表（approved）内。"""
from __future__ import annotations

import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select

from app.db import LabelVocab, SessionLocal
from app.ingest.tagger import get_vocab
from app.stores.graph import graph_store


def tag_pair(node: dict) -> tuple[str, str] | None:
    p = node.get("props") or {}
    cat, val = p.get("category"), p.get("value")
    if (not cat or not val) and node["id"].startswith("tag/") and ":" in node["id"]:
        cat, val = node["id"][4:].split(":", 1)
    if not cat or not val:
        return None
    return cat, val


def main() -> None:
    vocab = get_vocab(approved_only=True)
    vocab_any = get_vocab(approved_only=False)
    approved = {(c, v) for c, vs in vocab.items() for v in vs}
    any_set = {(c, v) for c, vs in vocab_any.items() for v in vs}

    with SessionLocal() as db:
        rows = db.execute(select(LabelVocab)).scalars().all()
    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        by_status[r.status] += 1

    print("=== LabelVocab ===")
    print("approved_by_category:", {c: len(vs) for c, vs in sorted(vocab.items())})
    print("approved_total:", len(approved))
    print("db_status:", dict(by_status))

    tags = [n for n in graph_store._nodes.values() if n.get("label") == "Tag"]
    in_ok, not_ok, missing = [], [], []
    for n in tags:
        pair = tag_pair(n)
        if pair is None:
            missing.append(n["id"])
            continue
        cat, val = pair
        item = {
            "id": n["id"],
            "category": cat,
            "value": val,
            "source": (n.get("props") or {}).get("source"),
            "verified": (n.get("props") or {}).get("verified"),
            "in_any": pair in any_set,
        }
        (in_ok if pair in approved else not_ok).append(item)

    print("\n=== Graph Tag nodes ===")
    print("total:", len(tags))
    print("in_approved:", len(in_ok))
    print("NOT_in_approved:", len(not_ok))
    print("missing_category_value:", len(missing))

    print("\n--- Tag nodes NOT in approved vocab ---")
    for it in sorted(not_ok, key=lambda x: (x["category"], x["value"])):
        print(
            f"  {it['category']}:{it['value']}"
            f"  source={it['source']} verified={it['verified']} in_db_any={it['in_any']}"
        )

    tagged = [e for e in graph_store._edges if e.get("rel") == "TAGGED"]
    bad_edges = []
    for e in tagged:
        dst = graph_store.node(e["dst"])
        if not dst:
            bad_edges.append((e["src"], e["dst"], "missing_dst_node"))
            continue
        pair = tag_pair(dst)
        if pair is None or pair not in approved:
            bad_edges.append(
                (e["src"], e["dst"], f"{pair[0]}:{pair[1]}" if pair else "bad_tag")
            )

    print("\n=== TAGGED edges ===")
    print("total:", len(tagged))
    print("with_tag_NOT_in_approved:", len(bad_edges))
    for src, dst, reason in bad_edges[:40]:
        print(f"  {src} -TAGGED-> {dst}  ({reason})")
    if len(bad_edges) > 40:
        print(f"  ... and {len(bad_edges) - 40} more")

    st = graph_store.stats()
    print("\n=== Scope note ===")
    print("graph_stats:", st)
    print(
        "词表封闭集只约束 Tag/TAGGED；"
        "CALLS/READS/PART_OF 等结构三元组不属于标签词表检查范围。"
    )
    conform = len(not_ok) == 0 and len(bad_edges) == 0 and len(missing) == 0
    print("\nVERDICT:", "ALL_TAG_TRIPLES_CONFORM" if conform else "NONCONFORMING_TAGS_FOUND")


if __name__ == "__main__":
    main()
