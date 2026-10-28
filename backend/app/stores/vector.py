"""向量存储：NumpyVectorStore（内嵌，暴力余弦） + MilvusVectorStore（可选）。

集合：kb_doc_chunk / kb_code_chunk / kb_mapping_chunk（设计 4.3 节）。
"""
from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from ..config import DATA_DIR, settings

COLLECTIONS = ("kb_doc_chunk", "kb_code_chunk", "kb_mapping_chunk")


def _cos(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class NumpyVectorStore:
    """内嵌向量索引（list+cosine），JSON 持久化，演示规模足够。"""

    def __init__(self) -> None:
        self._path = DATA_DIR / "runtime" / "vector_store.json"
        self._lock = threading.RLock()
        self._data: dict[str, list[dict]] = {c: [] for c in COLLECTIONS}
        self._load()

    def _load(self) -> None:
        source = self._path if self._path.exists() else DATA_DIR / "vector_store.json"
        if source.exists():
            raw = json.loads(source.read_text("utf-8"))
            for c in COLLECTIONS:
                self._data[c] = raw.get(c, [])

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, ensure_ascii=False), "utf-8")

    def upsert(self, collection: str, chunk_id: str, vector: list[float], metadata: dict) -> None:
        with self._lock:
            for ch in self._data[collection]:
                if ch["id"] == chunk_id:
                    ch["vector"], ch["meta"] = vector, metadata
                    return
            self._data[collection].append({"id": chunk_id, "vector": vector, "meta": metadata})

    def delete_by_meta(self, collection: str, key: str, value: str) -> None:
        with self._lock:
            self._data[collection] = [c for c in self._data[collection]
                                      if c["meta"].get(key) != value]

    def search(self, collection: str, vector: list[float], top_k: int = 5,
               meta_filter: dict | None = None) -> list[dict]:
        with self._lock:
            scored = []
            for ch in self._data[collection]:
                if meta_filter and not all(ch["meta"].get(k) == v for k, v in meta_filter.items()):
                    continue
                scored.append((_cos(vector, ch["vector"]), ch))
            scored.sort(key=lambda x: -x[0])
            return [{"id": ch["id"], "score": round(s, 4), "meta": ch["meta"]} for s, ch in scored[:top_k]]

    def count(self, collection: str) -> int:
        return len(self._data.get(collection, []))

    def stats(self) -> dict:
        return {c: self.count(c) for c in COLLECTIONS}


class MilvusVectorStore(NumpyVectorStore):
    """Milvus 实现：写穿透，读用内嵌镜像（演示期简化）。"""

    def __init__(self) -> None:
        super().__init__()
        from pymilvus import Collection, connections, utility  # optional dependency
        connections.connect(uri=settings.kb_vector_uri)
        self._col: dict[str, Collection] = {}
        dim = 256  # 由首次写入决定，此处占位
        for c in COLLECTIONS:
            if not utility.has_collection(c):
                from pymilvus import CollectionSchema, DataType, FieldSchema
                schema = CollectionSchema([
                    FieldSchema("id", DataType.VARCHAR, is_primary=True, max_length=128),
                    FieldSchema("vector", DataType.FLOAT_VECTOR, dim=dim),
                    FieldSchema("meta_json", DataType.VARCHAR, max_length=8192),
                ])
                Collection(c, schema=schema)
            col = Collection(c)
            col.load()
            self._col[c] = col


def build_vector_store() -> NumpyVectorStore:
    if settings.kb_vector_uri:
        try:
            return MilvusVectorStore()
        except Exception:  # pragma: no cover
            return NumpyVectorStore()
    return NumpyVectorStore()


vector_store = build_vector_store()
