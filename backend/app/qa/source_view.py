"""依据来源文档预览：按 path / 答案溯源条目解析全文。"""
from __future__ import annotations

from pathlib import Path

from ..config import DATA_DIR, SEED_DIR
from ..ingest.clean import default_dataset_root
from ..stores.graph import graph_store
from ..stores.objects import object_store
from ..stores.vector import vector_store

MAX_CHARS = 80_000


def _read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _resolve_file(path_hint: str) -> tuple[str | None, str]:
    """返回 (content, resolved_path)。"""
    hint = (path_hint or "").strip().replace("\\", "/").lstrip("/")
    if not hint:
        return None, ""

    # 1) 对象存储（kb-raw/...）
    if hint.startswith("kb-raw/") or object_store.exists(hint):
        text = object_store.get_text(hint)
        if text is not None:
            return text, hint

    # 2) hf_data 相对路径
    ds = default_dataset_root()
    p = ds / hint
    text = _read_text(p)
    if text is not None:
        return text, str(p)

    # 3) 仅文件名 → seed / objects 递归匹配
    name = Path(hint).name
    for root in (SEED_DIR, DATA_DIR / "objects", ds):
        if not root.exists():
            continue
        hits = list(root.rglob(name))
        if hits:
            text = _read_text(hits[0])
            if text is not None:
                return text, str(hits[0])

    # 4) 绝对路径（本机）
    abs_p = Path(path_hint)
    if abs_p.is_file():
        text = _read_text(abs_p)
        if text is not None:
            return text, str(abs_p)

    return None, hint


def _chunks_for_path(path_hint: str) -> str:
    """向量库中同 path 的 chunk 拼合作为降级全文。"""
    hint = (path_hint or "").replace("\\", "/")
    parts: list[str] = []
    for col in ("kb_doc_chunk", "kb_code_chunk", "kb_mapping_chunk"):
        for ch in getattr(vector_store, "_data", {}).get(col, []):
            meta = ch.get("meta") or {}
            sp = str(meta.get("source_path") or "").replace("\\", "/")
            if not sp:
                continue
            if sp == hint or sp.endswith("/" + hint) or hint.endswith(sp) or Path(sp).name == Path(hint).name:
                t = meta.get("text") or ""
                if t:
                    loc = meta.get("loc") or meta.get("title") or ""
                    parts.append(f"<!-- {loc} -->\n{t}" if loc else t)
    return "\n\n---\n\n".join(parts)


def _graph_doc(ref: str, source: dict | None = None) -> dict:
    name = ref or (source or {}).get("ref") or ""
    nodes = graph_store.find_by_name(name) if name else []
    node = nodes[0] if nodes else None
    if node is None and source and source.get("obj"):
        node = graph_store.node(source["obj"])
    lines = []
    if node:
        lines.append(f"# 图谱实体：{node['props'].get('name', node['id'])}")
        lines.append(f"类型：{node['label']}")
        lines.append(f"ID：{node['id']}")
        lines.append("")
        for k, v in (node.get("props") or {}).items():
            if v is None or v == "":
                continue
            lines.append(f"- {k}: {v}")
        ns, es = graph_store.neighbors(node["id"], max_hops=1)
        if es:
            lines.append("")
            lines.append("## 邻接关系")
            for e in es[:30]:
                dst = graph_store.node(e["dst"])
                dname = (dst or {}).get("props", {}).get("name", e["dst"])
                lines.append(f"- {e['rel']} → {dname}")
    body = "\n".join(lines) if lines else (source or {}).get("snippet") or "未找到图谱实体详情"
    return {
        "title": name or "图谱依据",
        "path": f"graph://{(node or {}).get('id', name)}",
        "loc": (source or {}).get("loc") or "",
        "type": "graph",
        "content": body[:MAX_CHARS],
        "from_cache": False,
        "available": bool(lines or (source or {}).get("snippet")),
    }


def preview_source(
    *,
    path: str = "",
    source_type: str = "doc",
    ref: str = "",
    loc: str = "",
    snippet: str = "",
    obj: str = "",
    label: str = "",
) -> dict:
    """统一预览入口。"""
    st = (source_type or "doc").lower()
    path_hint = path or obj or ""
    # label 有时是完整 source_path
    if not path_hint and label and ("/" in label or "\\" in label):
        path_hint = label

    if st == "graph":
        return _graph_doc(ref, {
            "ref": ref, "obj": obj, "loc": loc, "snippet": snippet, "label": label,
        })

    content, resolved = _resolve_file(path_hint)
    from_cache = False
    if content is None and path_hint:
        content = _chunks_for_path(path_hint)
        from_cache = bool(content)
        if content:
            resolved = path_hint

    if content is None and snippet:
        content = snippet
        from_cache = True
        resolved = resolved or path_hint or ref

    title = ref or Path(resolved or path_hint or "依据文档").name
    return {
        "title": title,
        "path": resolved or path_hint,
        "loc": loc,
        "type": st,
        "content": (content or "暂无法加载该依据原文，仅保留检索片段。")[:MAX_CHARS],
        "from_cache": from_cache,
        "available": bool(content),
        "snippet": (snippet or "")[:400],
    }
