"""向量存储：NumpyVectorStore（内嵌，暴力余弦） + MilvusVectorStore（可选）。

集合：kb_doc_chunk / kb_code_chunk / kb_mapping_chunk（设计 4.3 节）。
"""
from __future__ import annotations

import json
import math
import threading
import os
from copy import deepcopy
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


def _passage_scores(vector, passages):
    """Batch cosine on already-authorized passages, with a dependency-free fallback."""
    if not passages:
        return []
    try:
        import numpy as np
    except ImportError:
        return [max(_cos(vector, v) for v in p.get('vectors', [p['vector']])) for p in passages]
    query = np.asarray(vector, dtype=np.float64)
    query_norm = np.linalg.norm(query)
    if not query_norm:
        return [0.0] * len(passages)
    values, owners = [], []
    scores = np.full(len(passages), -np.inf)
    for i, passage in enumerate(passages):
        for value in passage.get('vectors', [passage['vector']]):
            if len(value) == len(vector):
                values.append(value)
                owners.append(i)
            else:
                scores[i] = 0.0  # Match the scalar path's dimension-mismatch behavior.
    if values:
        matrix = np.asarray(values, dtype=np.float64)
        denominator = np.linalg.norm(matrix, axis=1) * query_norm
        similarities = np.divide(matrix @ query, denominator,
            out=np.zeros(len(values)), where=denominator != 0)
        np.maximum.at(scores, owners, similarities)
    scores[np.isneginf(scores)] = 0.0
    return scores.tolist()


class NumpyVectorStore:
    """内嵌向量索引，批量余弦检索，JSON 持久化。"""

    def __init__(self) -> None:
        self._path = DATA_DIR / "runtime" / "vector_store.json"
        self._lock = threading.RLock()
        self._revision = 0
        self._manifest = {}
        self._data: dict[str, list[dict]] = {c: [] for c in COLLECTIONS}
        self._load()

    def _load(self) -> None:
        source = self._path
        if source.exists():
            raw = json.loads(source.read_text("utf-8"))
            self._manifest = raw.get('__manifest', {})
            for c in COLLECTIONS:
                self._data[c] = raw.get(c, [])

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(f'.{os.getpid()}.tmp')
            temporary.write_text(json.dumps({**self._data,'__manifest':self._manifest}, ensure_ascii=False), "utf-8")
            temporary.replace(self._path)

    def export(self, collection: str, meta_filter: dict | None = None):
        with self._lock:
            return deepcopy([row for row in self._data[collection]
                if not meta_filter or all(row['meta'].get(k) == v for k, v in meta_filter.items())])

    def replace_all(self, data, expected_revision=None, manifest=None):
        """Publish one fully validated generation, leaving live data intact on failure."""
        from ..ingest.quality import validate_embeddings
        data = dict(data)
        saved_manifest = data.pop('__manifest', {})
        manifest = manifest if manifest is not None else saved_manifest
        for rows in data.values():
            for row in rows:
                validate_embeddings([row['vector']], 1)
                for child in row['meta'].get('children', []):
                    if not child.get('vectors'):
                        raise ValueError('检索子块缺少有效向量')
                    validate_embeddings(child['vectors'], len(child['vectors']))
        with self._lock:
            if expected_revision is not None and expected_revision != self._revision:
                raise ValueError('构建期间知识索引已变化，请基于新快照重建')
            previous = self._data
            previous_manifest = self._manifest
            self._data = data
            self._manifest = manifest
            try:
                self.save()
            except Exception:
                self._data = previous
                self._manifest = previous_manifest
                raise
            self._revision += 1

    @property
    def manifest(self):
        with self._lock:
            return dict(self._manifest)

    @staticmethod
    def passages(row):
        children = row['meta'].get('children')
        if not children:
            return [row]
        return [dict(id=child['id'], vector=child['vectors'][0], vectors=child['vectors'],
            meta={**{k:v for k,v in row['meta'].items() if k != 'children'},
                  **{k:v for k,v in child.items() if k not in {'id', 'vectors'}},
                  'title':Path(row['meta'].get('source_path','')).name if str(child.get('parent_id','')).startswith('overview-') else row['meta'].get('title',''),
                  'parent_id':child.get('parent_id') or row['id']}) for child in children]

    def upsert(self, collection: str, chunk_id: str, vector: list[float], metadata: dict) -> None:
        with self._lock:
            self._revision += 1
            for ch in self._data[collection]:
                if ch["id"] == chunk_id:
                    ch["vector"], ch["meta"] = vector, metadata
                    return
            self._data[collection].append({"id": chunk_id, "vector": vector, "meta": metadata})

    def delete_by_meta(self, collection: str, key: str, value: str) -> None:
        with self._lock:
            self._revision += 1
            self._data[collection] = [c for c in self._data[collection]
                                      if c["meta"].get(key) != value]

    def delete_ids(self, collection: str, ids: set[str]) -> None:
        with self._lock:
            self._revision += 1
            self._data[collection] = [c for c in self._data[collection] if c['id'] not in ids]

    def search(self, collection: str, vector: list[float], top_k: int = 5,
               meta_filter: dict | None = None, exclude_paths=None) -> list[dict]:
        with self._lock:
            current = None
            if any(ch['meta'].get('project_job') for ch in self._data.get(collection, [])):
                from ..knowledge.catalog import current_project_jobs
                current = current_project_jobs()
            passages = []
            for ch in self._data[collection]:
                if ch['meta'].get('source_path', '') in (exclude_paths or set()):
                    continue
                if current is not None and ch['meta'].get('project_job') and ch['meta']['project_job'] not in current:
                    continue
                if meta_filter and not all(ch["meta"].get(k) == v for k, v in meta_filter.items()):
                    continue
                passages.extend(self.passages(ch))
            # ACL and current-version filters above must run before both scoring and top-k.
            scored = list(zip(_passage_scores(vector, passages), passages))
            scored.sort(key=lambda x: -x[0])
            return [{"id": ch["id"], "score": round(s, 4), "meta": ch["meta"]} for s, ch in scored[:top_k]]

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def metadata_snapshot(self, collection: str) -> tuple[int, list[dict]]:
        """A consistent read for the lexical index; do not expose vectors or mutable rows."""
        with self._lock:
            return self._revision, [dict(id=p['id'], meta=dict(p['meta'])) for row in self._data.get(collection, []) for p in self.passages(row)]

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
