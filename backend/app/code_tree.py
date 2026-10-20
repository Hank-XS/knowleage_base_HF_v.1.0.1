"""从 hf_data/02_code_assets 扫描目录与程序结构，生成代码树。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .ingest.clean import default_dataset_root

_EXT_LANG = {
    ".cbl": "cobol", ".cob": "cobol", ".cpy": "copybook",
    ".jcl": "jcl", ".rpgle": "rpg", ".sql": "sql",
    ".sh": "shell", ".rex": "rexx", ".mqsc": "mqsc",
    ".xml": "cics", ".csv": "data", ".json": "json",
    ".md": "doc", ".txt": "doc",
}

_PARA_RE = re.compile(
    r"^\s{0,11}([0-9]{3,4}-[A-Z0-9][A-Z0-9-]*)\s*\.\s*$", re.I)
_SECTION_RE = re.compile(
    r"^\s{0,11}([A-Z][A-Z0-9-]*)\s+SECTION\b", re.I)
_PROG_RE = re.compile(r"PROGRAM-ID\.\s*([A-Z0-9][A-Z0-9-]*)", re.I)
_CALL_RE = re.compile(r"\bCALL\s+['\"]([A-Z][A-Z0-9-]{1,})", re.I)
_COPY_RE = re.compile(r"\bCOPY\s+([A-Z0-9][A-Z0-9-]*)", re.I)
_JCL_STEP_RE = re.compile(r"^//([A-Z0-9$#@]{1,8})\s+EXEC\b", re.I)
_SQL_PROC_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+([A-Z0-9_]+)", re.I)

_SKIP_DIR = {".git", "__pycache__", "node_modules"}


def code_assets_root() -> Path:
    return default_dataset_root() / "02_code_assets"


def _safe_file(rel: str) -> Path:
    rel_n = (rel or "").replace("\\", "/").lstrip("/")
    if not rel_n or ".." in rel_n.split("/"):
        raise ValueError("非法路径")
    base = code_assets_root().resolve()
    target = (base / rel_n).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("非法路径")
    if not target.is_file():
        raise ValueError("文件不存在")
    return target


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _uniq(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        k = x.upper()
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _inspect_source(path: Path, lang: str) -> dict[str, Any]:
    text = _read_text(path)
    lines = text.splitlines()
    program = path.stem.upper()
    m = _PROG_RE.search(text)
    if m:
        program = m.group(1).upper()

    symbols: list[dict] = []
    calls: list[str] = []
    copies: list[str] = []

    if lang in ("cobol", "copybook"):
        for i, line in enumerate(lines, start=1):
            pm = _PARA_RE.match(line) or (
                _SECTION_RE.match(line) if "SECTION" in line.upper() else None)
            if pm:
                name = pm.group(1).upper()
                if name in (
                    "PROGRAM-ID", "WORKING-STORAGE", "FILE", "LINKAGE",
                    "PROCEDURE", "ENVIRONMENT", "IDENTIFICATION", "DATA",
                    "CONFIGURATION", "INPUT-OUTPUT", "LOCAL-STORAGE",
                ):
                    continue
                symbols.append({"name": name, "line": i, "kind": "paragraph"})
            for c in _CALL_RE.findall(line):
                calls.append(c)
            for cp in _COPY_RE.findall(line):
                copies.append(cp)
    elif lang == "jcl":
        for i, line in enumerate(lines, start=1):
            sm = _JCL_STEP_RE.match(line)
            if sm and sm.group(1).upper() not in ("*",):
                symbols.append({
                    "name": sm.group(1).upper(), "line": i, "kind": "step",
                })
    elif lang == "sql":
        for i, line in enumerate(lines, start=1):
            sm = _SQL_PROC_RE.search(line)
            if sm:
                symbols.append({
                    "name": sm.group(1).upper(), "line": i, "kind": "procedure",
                })

    # 段名去重（保留首次出现行）
    seen, uniq_sym = set(), []
    for s in symbols:
        if s["name"] in seen:
            continue
        seen.add(s["name"])
        uniq_sym.append(s)

    return {
        "program": program,
        "lines": len(lines),
        "symbols": uniq_sym,
        "calls": _uniq(calls),
        "copies": _uniq(copies),
    }


def _file_node(path: Path, rel: str) -> dict:
    lang = _EXT_LANG.get(path.suffix.lower(), "other")
    info = _inspect_source(path, lang) if lang in (
        "cobol", "copybook", "jcl", "sql") else {
        "program": path.stem.upper(),
        "lines": sum(1 for _ in path.open(encoding="utf-8", errors="replace")),
        "symbols": [],
        "calls": [],
        "copies": [],
    }
    title = path.name
    if lang == "cobol":
        title = f"{info['program']}  ({path.name})"
    children = [
        {
            "key": f"{rel}#{s['name']}",
            "title": s["name"],
            "kind": s["kind"],
            "line": s["line"],
            "path": rel,
            "isLeaf": True,
        }
        for s in info["symbols"]
    ]
    node: dict[str, Any] = {
        "key": rel,
        "title": title,
        "kind": "program" if lang == "cobol" else "file",
        "lang": lang,
        "path": rel,
        "program": info["program"],
        "lines": info["lines"],
        "calls": info["calls"],
        "copies": info["copies"],
        "symbol_count": len(info["symbols"]),
        "isLeaf": not children,
    }
    if children:
        node["children"] = children
    return node


def _dir_node(name: str, key: str, children: list[dict]) -> dict:
    files = sum(1 for c in children if c.get("kind") in ("file", "program"))
    nested = sum(c.get("file_count", 0) for c in children if c.get("kind") == "dir")
    return {
        "key": key or name,
        "title": name,
        "kind": "dir",
        "file_count": files + nested,
        "children": children,
    }


def _walk(directory: Path, prefix: str) -> list[dict]:
    dirs, files = [], []
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith(".") or entry.name in _SKIP_DIR:
            continue
        rel = f"{prefix}/{entry.name}" if prefix else entry.name
        if entry.is_dir():
            kids = _walk(entry, rel)
            if kids:
                dirs.append(_dir_node(entry.name, rel, kids))
        elif entry.is_file():
            files.append(_file_node(entry, rel.replace("\\", "/")))
    return dirs + files


def build_code_tree() -> dict[str, Any]:
    root = code_assets_root()
    if not root.is_dir():
        return {
            "root": str(root),
            "found": False,
            "tree": [],
            "stats": {"files": 0, "programs": 0, "dirs": 0},
        }
    tree = _walk(root, "")

    def _count(nodes: list[dict]) -> tuple[int, int, int]:
        files = programs = dirs = 0
        for n in nodes:
            if n.get("kind") == "dir":
                dirs += 1
                f, p, d = _count(n.get("children") or [])
                files += f
                programs += p
                dirs += d
            elif n.get("kind") == "program":
                files += 1
                programs += 1
            elif n.get("kind") == "file":
                files += 1
        return files, programs, dirs

    files, programs, dirs = _count(tree)
    return {
        "root": "02_code_assets",
        "found": True,
        "tree": tree,
        "stats": {"files": files, "programs": programs, "dirs": dirs},
    }


def preview_source(rel: str, symbol: str = "",
                   max_lines: int = 12_000) -> dict[str, Any]:
    """预览源码：点程序显示全文；点段名时从该段到下一段（仍可很长）。"""
    path = _safe_file(rel)
    text = _read_text(path)
    lines = text.splitlines()
    total = len(lines)
    focus = 1
    start, end = 1, total

    if symbol:
        sym = symbol.upper()
        for i, line in enumerate(lines, start=1):
            head = (_PARA_RE.match(line) or _SECTION_RE.match(line)
                    or _JCL_STEP_RE.match(line))
            if head and head.group(1).upper() == sym:
                focus = i
                break
        start = focus
        # 段尾：下一 paragraph/section/step，否则到文件末
        end = total
        for j in range(focus + 1, total + 1):
            head = (_PARA_RE.match(lines[j - 1]) or _SECTION_RE.match(lines[j - 1])
                    or _JCL_STEP_RE.match(lines[j - 1]))
            if head and head.group(1).upper() != sym:
                end = j - 1
                break
        # 段过短时多给一点下文，避免只剩段名一行
        if end - start < 15:
            end = min(total, start + 40)

    # 安全上限，避免超大文件撑爆响应
    truncated = False
    if end - start + 1 > max_lines:
        end = start + max_lines - 1
        truncated = True

    raw_lines = [lines[i - 1] for i in range(start, end + 1)]
    snippet = "\n".join(f"{i:4d} | {lines[i - 1]}" for i in range(start, end + 1))
    return {
        "path": rel.replace("\\", "/"),
        "name": path.name,
        "lines": total,
        "start_line": start,
        "end_line": end,
        "focus_line": focus,
        "truncated": truncated,
        "snippet": snippet,
        "raw": "\n".join(raw_lines) + ("\n" if text.endswith("\n") and end == total else ""),
    }
