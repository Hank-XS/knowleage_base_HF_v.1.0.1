"""知识库管理：从 hf_data 同步、文档 CRUD、切片、版本对比、代码映射。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select

from ..db import (
    KbDocChunk,
    KbDocVersion,
    KbDocument,
    KbLibrary,
    SessionLocal,
)
from ..ingest.clean import default_dataset_root
from ..stores.objects import object_store

TEXT_EXTS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".xml",
    ".cbl", ".cob", ".cpy", ".jcl", ".sql", ".sh", ".rex",
    ".rpgle", ".mqsc", ".java", ".py", ".ts", ".js", ".html",
    ".ini", ".mmd",
}

SKIP_DIRS = {"08_cleaned", ".git", "__pycache__", "node_modules"}

LIBRARY_TITLES = {
    "01_tech_docs": "技术文档",
    "02_code_assets": "代码资产",
    "03_business_rules": "业务规则",
    "04_system_metadata": "系统元数据",
    "07_derived": "衍生补全",
}


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{max(1, n // 1024)}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def split_chunks(content: str, *, max_len: int = 900) -> list[dict[str, Any]]:
    """按 Markdown 标题或固定长度切片。"""
    text = (content or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    parts: list[tuple[str, str]] = []
    # ## 标题分段
    blocks = re.split(r"(?m)^(#{1,3}\s+.+)$", text)
    if len(blocks) > 1:
        cur_title = "正文"
        buf: list[str] = []
        for i, blk in enumerate(blocks):
            if re.match(r"^#{1,3}\s+", blk or ""):
                if buf:
                    parts.append((cur_title, "".join(buf).strip()))
                    buf = []
                cur_title = re.sub(r"^#{1,3}\s+", "", blk).strip() or "章节"
            else:
                buf.append(blk or "")
        if buf:
            parts.append((cur_title, "".join(buf).strip()))
    else:
        parts = [("全文", text)]

    chunks: list[dict[str, Any]] = []
    offset = 0
    idx = 0
    for title, body in parts:
        if not body:
            continue
        start = 0
        while start < len(body):
            piece = body[start : start + max_len]
            # 尽量在段落边界断开
            if start + max_len < len(body):
                cut = piece.rfind("\n\n")
                if cut > max_len // 3:
                    piece = piece[:cut]
            abs_start = text.find(piece, offset)
            if abs_start < 0:
                abs_start = offset
            abs_end = abs_start + len(piece)
            chunks.append({
                "chunk_index": idx,
                "title": title if start == 0 else f"{title} (续)",
                "text": piece.strip(),
                "start_offset": abs_start,
                "end_offset": abs_end,
            })
            idx += 1
            offset = abs_end
            start += max(len(piece), 1)
    return [c for c in chunks if c["text"]]


def _ensure_library(
    db,
    key: str,
    title: str,
    parent_key: str = "",
    *,
    seen: set[str] | None = None,
) -> None:
    if seen is not None and key in seen:
        return
    row = db.get(KbLibrary, key)
    if row is None:
        db.add(KbLibrary(key=key, title=title, parent_key=parent_key or ""))
        db.flush()
    else:
        row.title = title
        row.parent_key = parent_key or ""
    if seen is not None:
        seen.add(key)


def sync_from_dataset(force: bool = False) -> dict[str, Any]:
    """扫描 hf_data，写入文档/版本/切片。已有数据且非 force 则跳过。"""
    root = default_dataset_root()
    with SessionLocal() as db:
        count = db.execute(select(func.count()).select_from(KbDocument)).scalar() or 0
        if count > 0 and not force:
            return {"synced": False, "reason": "already_synced", "docs": count}

        if force:
            db.query(KbDocChunk).delete()
            db.query(KbDocVersion).delete()
            db.query(KbDocument).delete()
            db.query(KbLibrary).delete()
            db.commit()

        if not root.exists():
            return {"synced": False, "reason": "dataset_missing", "root": str(root)}

        docs_created = 0
        seen_libs: set[str] = set()
        for top in sorted(root.iterdir()):
            if not top.is_dir() or top.name in SKIP_DIRS or top.name.startswith("."):
                continue
            lib_key = top.name
            _ensure_library(
                db, lib_key, LIBRARY_TITLES.get(lib_key, lib_key), "", seen=seen_libs,
            )
            # 二级目录
            for child in sorted(top.iterdir()):
                if child.is_dir() and child.name not in SKIP_DIRS:
                    child_key = f"{lib_key}/{child.name}"
                    _ensure_library(db, child_key, child.name, lib_key, seen=seen_libs)

            for path in top.rglob("*"):
                if not path.is_file():
                    continue
                if any(p in SKIP_DIRS for p in path.parts):
                    continue
                if path.suffix.lower() not in TEXT_EXTS:
                    continue
                if path.stat().st_size > 2_000_000:
                    continue
                rel = path.relative_to(root).as_posix()
                parts = rel.split("/")
                library_key = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
                parent = parts[0]
                title = parts[1] if len(parts) > 1 else parts[0]
                _ensure_library(db, library_key, title, parent if "/" in library_key else "", seen=seen_libs)

                content = _read_text(path)
                name = path.stem
                doc_type = path.suffix.lower().lstrip(".") or "txt"
                exists = db.execute(
                    select(KbDocument).where(
                        KbDocument.library_key == library_key,
                        KbDocument.path == rel,
                    )
                ).scalar_one_or_none()
                if exists:
                    continue

                version = "v1.0"
                # 尝试从正文抽版本
                m = re.search(r"(?i)版本\s*[|:：]?\s*(V?\d+(?:\.\d+)*)", content[:800])
                if m:
                    ver = m.group(1)
                    version = ver if ver.lower().startswith("v") else f"v{ver}"

                obj_key = object_store.put_text(
                    f"kb-managed/{library_key}/{path.name}", content
                )
                doc = KbDocument(
                    library_key=library_key,
                    path=rel,
                    name=name,
                    doc_type=doc_type,
                    version=version,
                    status="published" if "02_code_assets" in rel else "draft",
                    vectorized=1 if "08_cleaned" not in rel else 0,
                    official=1,
                    security="internal" if "ticket" in rel.lower() else "public",
                    size_bytes=len(content.encode("utf-8")),
                    object_key=obj_key,
                    source_path=rel,
                    author="system",
                    tags_json=[],
                )
                db.add(doc)
                db.flush()
                db.add(KbDocVersion(
                    doc_id=doc.id, version=version, content=content, created_by="system",
                ))
                for ch in split_chunks(content):
                    db.add(KbDocChunk(
                        doc_id=doc.id,
                        version=version,
                        chunk_index=ch["chunk_index"],
                        title=ch["title"][:256],
                        text=ch["text"],
                        start_offset=ch["start_offset"],
                        end_offset=ch["end_offset"],
                    ))
                docs_created += 1

        db.commit()
        return {"synced": True, "docs": docs_created, "root": str(root)}


def ensure_synced() -> None:
    sync_from_dataset(force=False)


def library_tree() -> list[dict[str, Any]]:
    ensure_synced()
    with SessionLocal() as db:
        libs = db.execute(select(KbLibrary).order_by(KbLibrary.key)).scalars().all()
        counts = dict(
            db.execute(
                select(KbDocument.library_key, func.count())
                .group_by(KbDocument.library_key)
            ).all()
        )
        # 父节点计数 = 自身 + 子
        all_keys = [x.key for x in libs]
        total_for: dict[str, int] = {k: 0 for k in all_keys}
        for k, c in counts.items():
            total_for[k] = total_for.get(k, 0) + int(c)
            parent = k.split("/")[0] if "/" in k else ""
            if parent and parent in total_for and parent != k:
                # 仅一级累计到根
                pass
        # 重新：根节点 = 所有以该 key 开头的文档
        root_counts: dict[str, int] = {}
        docs = db.execute(select(KbDocument.library_key)).scalars().all()
        for lk in docs:
            root = lk.split("/")[0]
            root_counts[root] = root_counts.get(root, 0) + 1
            root_counts[lk] = root_counts.get(lk, 0) + 1

        nodes = []
        for lib in libs:
            if lib.parent_key:
                continue
            children = [
                {
                    "key": c.key,
                    "title": c.title,
                    "count": root_counts.get(c.key, 0),
                    "children": [],
                }
                for c in libs
                if c.parent_key == lib.key
            ]
            nodes.append({
                "key": lib.key,
                "title": lib.title,
                "count": root_counts.get(lib.key, 0),
                "children": children,
            })
        return nodes


def _doc_payload(doc: KbDocument, *, content: str | None = None) -> dict[str, Any]:
    payload = {
        "id": doc.id,
        "name": doc.name,
        "type": doc.doc_type,
        "version": doc.version,
        "status": doc.status,
        "vectorized": bool(doc.vectorized),
        "official": bool(doc.official),
        "security": doc.security,
        "size": _human_size(doc.size_bytes or 0),
        "size_bytes": doc.size_bytes,
        "uploadedAt": doc.uploaded_at.isoformat(sep=" ", timespec="seconds") if doc.uploaded_at else "",
        "kbKey": doc.library_key.split("/")[0],
        "path": doc.library_key,
        "sourcePath": doc.source_path,
        "author": doc.author,
        "tags": doc.tags_json or [],
    }
    if content is not None:
        payload["content"] = content
    return payload


def list_docs(
    *,
    kb: str = "",
    keyword: str = "",
    doc_type: str = "",
    status: str = "",
    version: str = "",
    vectorized: str = "",
    official: str = "",
    security: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    ensure_synced()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    with SessionLocal() as db:
        q = select(KbDocument)
        if kb:
            if "/" in kb:
                q = q.where(KbDocument.library_key == kb)
            else:
                q = q.where(
                    or_(
                        KbDocument.library_key == kb,
                        KbDocument.library_key.like(f"{kb}/%"),
                    )
                )
        if keyword:
            like = f"%{keyword}%"
            q = q.where(or_(KbDocument.name.like(like), KbDocument.path.like(like)))
        if doc_type:
            q = q.where(KbDocument.doc_type == doc_type)
        if status:
            q = q.where(KbDocument.status == status)
        if version:
            q = q.where(KbDocument.version == version)
        if vectorized == "yes":
            q = q.where(KbDocument.vectorized == 1)
        elif vectorized == "no":
            q = q.where(KbDocument.vectorized == 0)
        if official == "yes":
            q = q.where(KbDocument.official == 1)
        elif official == "no":
            q = q.where(KbDocument.official == 0)
        if security:
            q = q.where(KbDocument.security == security)

        total = db.execute(select(func.count()).select_from(q.subquery())).scalar() or 0
        rows = db.execute(
            q.order_by(KbDocument.uploaded_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
        return {
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "items": [_doc_payload(r) for r in rows],
        }


def get_doc(doc_id: str, *, with_content: bool = True) -> dict[str, Any] | None:
    with SessionLocal() as db:
        doc = db.get(KbDocument, doc_id)
        if not doc:
            return None
        content = None
        if with_content:
            ver = db.execute(
                select(KbDocVersion).where(
                    KbDocVersion.doc_id == doc_id,
                    KbDocVersion.version == doc.version,
                )
            ).scalar_one_or_none()
            content = ver.content if ver else ""
        return _doc_payload(doc, content=content)


def delete_doc(doc_id: str) -> bool:
    with SessionLocal() as db:
        doc = db.get(KbDocument, doc_id)
        if not doc:
            return False
        db.query(KbDocChunk).filter(KbDocChunk.doc_id == doc_id).delete()
        db.query(KbDocVersion).filter(KbDocVersion.doc_id == doc_id).delete()
        db.delete(doc)
        db.commit()
        return True


def batch_update_status(doc_ids: list[str], status: str) -> int:
    if status not in {"draft", "review", "published"}:
        raise ValueError("invalid status")
    with SessionLocal() as db:
        n = 0
        for did in doc_ids:
            doc = db.get(KbDocument, did)
            if doc:
                doc.status = status
                n += 1
        db.commit()
        return n


def create_library(key: str, title: str, parent_key: str = "") -> dict[str, Any]:
    key = key.strip().replace(" ", "-")
    if not key:
        raise ValueError("key required")
    with SessionLocal() as db:
        if db.get(KbLibrary, key):
            raise ValueError("library exists")
        if parent_key and not db.get(KbLibrary, parent_key):
            raise ValueError("parent not found")
        db.add(KbLibrary(key=key, title=title or key, parent_key=parent_key or ""))
        db.commit()
        return {"key": key, "title": title or key, "parent_key": parent_key or ""}


def upload_document(
    *,
    filename: str,
    content: bytes,
    library_key: str,
    version: str,
    security: str = "public",
    author: str = "admin",
    tags: list[str] | None = None,
    official: bool = True,
    auto_chunk: bool = True,
) -> dict[str, Any]:
    ensure_synced()
    if not version:
        raise ValueError("version required")
    text = content.decode("utf-8", errors="replace")
    name = Path(filename).stem
    doc_type = Path(filename).suffix.lower().lstrip(".") or "txt"
    lib = library_key or "uploads"
    with SessionLocal() as db:
        if db.get(KbLibrary, lib.split("/")[0]) is None:
            _ensure_library(db, lib.split("/")[0], lib.split("/")[0], "")
        if "/" in lib and db.get(KbLibrary, lib) is None:
            _ensure_library(db, lib, lib.split("/")[-1], lib.split("/")[0])

        rel_path = f"uploads/{lib}/{filename}"
        existing = db.execute(
            select(KbDocument).where(
                KbDocument.library_key == lib,
                KbDocument.name == name,
            )
        ).scalar_one_or_none()

        obj_key = object_store.put(
            f"kb-managed/{lib}/{filename}", content
        )

        if existing:
            # 新版本
            existing.version = version
            existing.size_bytes = len(content)
            existing.object_key = obj_key
            existing.security = security
            existing.author = author
            existing.official = 1 if official else 0
            existing.tags_json = tags or []
            existing.status = "draft"
            existing.vectorized = 0
            doc = existing
            # 覆盖同版本或新增
            ver = db.execute(
                select(KbDocVersion).where(
                    KbDocVersion.doc_id == doc.id,
                    KbDocVersion.version == version,
                )
            ).scalar_one_or_none()
            if ver:
                ver.content = text
            else:
                db.add(KbDocVersion(
                    doc_id=doc.id, version=version, content=text, created_by=author,
                ))
            db.query(KbDocChunk).filter(
                KbDocChunk.doc_id == doc.id, KbDocChunk.version == version,
            ).delete()
        else:
            doc = KbDocument(
                library_key=lib,
                path=rel_path,
                name=name,
                doc_type=doc_type,
                version=version,
                status="draft",
                vectorized=0,
                official=1 if official else 0,
                security=security,
                size_bytes=len(content),
                object_key=obj_key,
                source_path=rel_path,
                author=author,
                tags_json=tags or [],
            )
            db.add(doc)
            db.flush()
            db.add(KbDocVersion(
                doc_id=doc.id, version=version, content=text, created_by=author,
            ))

        if auto_chunk:
            for ch in split_chunks(text):
                db.add(KbDocChunk(
                    doc_id=doc.id,
                    version=version,
                    chunk_index=ch["chunk_index"],
                    title=ch["title"][:256],
                    text=ch["text"],
                    start_offset=ch["start_offset"],
                    end_offset=ch["end_offset"],
                ))
            doc.vectorized = 1

        db.commit()
        db.refresh(doc)
        return _doc_payload(doc, content=text)


def list_chunks(doc_id: str, version: str = "", keyword: str = "") -> dict[str, Any]:
    with SessionLocal() as db:
        doc = db.get(KbDocument, doc_id)
        if not doc:
            return {"doc": None, "chunks": [], "content": ""}
        ver = version or doc.version
        vrow = db.execute(
            select(KbDocVersion).where(
                KbDocVersion.doc_id == doc_id, KbDocVersion.version == ver,
            )
        ).scalar_one_or_none()
        content = vrow.content if vrow else ""
        q = select(KbDocChunk).where(
            KbDocChunk.doc_id == doc_id, KbDocChunk.version == ver,
        ).order_by(KbDocChunk.chunk_index)
        rows = db.execute(q).scalars().all()
        items = []
        kw = keyword.strip().lower()
        for r in rows:
            if kw and kw not in r.id.lower() and kw not in (r.title or "").lower() and kw not in (r.text or "").lower():
                continue
            items.append({
                "id": r.id,
                "title": r.title,
                "text": r.text,
                "start": r.start_offset,
                "end": r.end_offset,
                "chunk_index": r.chunk_index,
            })
        return {
            "doc": _doc_payload(doc),
            "version": ver,
            "content": content,
            "chunks": items,
        }


def list_versions(doc_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.execute(
            select(KbDocVersion)
            .where(KbDocVersion.doc_id == doc_id)
            .order_by(KbDocVersion.created_at)
        ).scalars().all()
        return [
            {
                "version": r.version,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "chars": len(r.content or ""),
            }
            for r in rows
        ]


def diff_versions(doc_id: str, old: str, new: str) -> dict[str, Any]:
    with SessionLocal() as db:
        doc = db.get(KbDocument, doc_id)
        if not doc:
            return {"error": "not_found"}
        old_row = db.execute(
            select(KbDocVersion).where(
                KbDocVersion.doc_id == doc_id, KbDocVersion.version == old,
            )
        ).scalar_one_or_none()
        new_row = db.execute(
            select(KbDocVersion).where(
                KbDocVersion.doc_id == doc_id, KbDocVersion.version == new,
            )
        ).scalar_one_or_none()
        a = (old_row.content if old_row else "").replace("\r\n", "\n").split("\n")
        b = (new_row.content if new_row else "").replace("\r\n", "\n").split("\n")
        max_n = max(len(a), len(b))
        rows = []
        added = removed = modified = 0
        for i in range(max_n):
            L = a[i] if i < len(a) else None
            R = b[i] if i < len(b) else None
            if L is None and R is not None:
                typ = "add"
                added += 1
            elif R is None and L is not None:
                typ = "del"
                removed += 1
            elif L != R:
                typ = "mod"
                modified += 1
            else:
                typ = "same"
            rows.append({"left": L, "right": R, "type": typ})
        return {
            "doc": _doc_payload(doc),
            "old": old,
            "new": new,
            "stats": {"added": added, "removed": removed, "modified": modified},
            "rows": rows,
            "old_content": old_row.content if old_row else "",
            "new_content": new_row.content if new_row else "",
        }


def _program_name(path: str, name: str) -> str:
    base = Path(name).stem.upper()
    return re.sub(r"[^A-Z0-9_-]", "", base) or base


def list_code_files(kb: str = "") -> list[dict[str, Any]]:
    ensure_synced()
    code_types = {"cbl", "cob", "java", "py", "sql", "jcl"}
    with SessionLocal() as db:
        q = select(KbDocument).where(KbDocument.doc_type.in_(code_types))
        if kb:
            q = q.where(
                or_(
                    KbDocument.library_key == kb,
                    KbDocument.library_key.like(f"{kb}/%"),
                )
            )
        rows = db.execute(q.order_by(KbDocument.name).limit(200)).scalars().all()
        return [
            {
                "key": r.id,
                "label": f"{r.name}.{r.doc_type}",
                "version": r.version,
                "kb": r.library_key.split("/")[0],
                "path": r.source_path or r.path,
            }
            for r in rows
        ]


def code_map(doc_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        doc = db.get(KbDocument, doc_id)
        if not doc:
            return {"error": "not_found"}
        ver = db.execute(
            select(KbDocVersion).where(
                KbDocVersion.doc_id == doc_id,
                KbDocVersion.version == doc.version,
            )
        ).scalar_one_or_none()
        content = ver.content if ver else ""
        prog = _program_name(doc.path, doc.name)
        related = []
        if prog and len(prog) >= 3:
            # 在其它文档中查找程序名引用
            candidates = db.execute(
                select(KbDocument).where(KbDocument.id != doc_id).limit(500)
            ).scalars().all()
            for c in candidates:
                v = db.execute(
                    select(KbDocVersion).where(
                        KbDocVersion.doc_id == c.id,
                        KbDocVersion.version == c.version,
                    )
                ).scalar_one_or_none()
                body = (v.content if v else "") or ""
                if prog in body.upper() or prog in (c.name or "").upper():
                    # 找所在小节
                    section = "相关引用"
                    for line in body.splitlines():
                        if prog in line.upper():
                            section = line.strip()[:120]
                            break
                    related.append({
                        "id": c.id,
                        "name": f"{c.name}.{c.doc_type}",
                        "section": section,
                    })
                    if len(related) >= 20:
                        break
        return {
            "file": {
                "key": doc.id,
                "label": f"{doc.name}.{doc.doc_type}",
                "version": doc.version,
                "kb": doc.library_key.split("/")[0],
                "content": content,
            },
            "relatedDocs": related,
            "symbol": prog,
        }


def bump_demo_version(doc_id: str, new_version: str, append_note: str) -> dict[str, Any]:
    """测试/演示：为文档增加一个新版本（在旧内容后追加说明）。"""
    with SessionLocal() as db:
        doc = db.get(KbDocument, doc_id)
        if not doc:
            raise ValueError("not found")
        old = db.execute(
            select(KbDocVersion).where(
                KbDocVersion.doc_id == doc_id,
                KbDocVersion.version == doc.version,
            )
        ).scalar_one_or_none()
        base = old.content if old else ""
        content = f"{base.rstrip()}\n\n## 变更说明（{new_version}）\n\n{append_note}\n"
        exists = db.execute(
            select(KbDocVersion).where(
                KbDocVersion.doc_id == doc_id,
                KbDocVersion.version == new_version,
            )
        ).scalar_one_or_none()
        if exists:
            exists.content = content
        else:
            db.add(KbDocVersion(
                doc_id=doc_id, version=new_version, content=content, created_by="system",
            ))
        doc.version = new_version
        db.query(KbDocChunk).filter(
            KbDocChunk.doc_id == doc_id, KbDocChunk.version == new_version,
        ).delete()
        for ch in split_chunks(content):
            db.add(KbDocChunk(
                doc_id=doc_id,
                version=new_version,
                chunk_index=ch["chunk_index"],
                title=ch["title"][:256],
                text=ch["text"],
                start_offset=ch["start_offset"],
                end_offset=ch["end_offset"],
            ))
        db.commit()
        return _doc_payload(doc, content=content)
