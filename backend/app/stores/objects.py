"""对象存储：本地文件系统实现 + MinIO 可选。路径规范见设计 4.5 节。"""
from __future__ import annotations

import datetime as dt

from ..config import DATA_DIR, settings


class FSObjectStore:
    def __init__(self) -> None:
        self._root = DATA_DIR / "objects"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> "any":
        p = self._root / key.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put(self, key: str, content: bytes) -> str:
        self._path(key).write_bytes(content)
        return key

    def put_text(self, key: str, text: str) -> str:
        self._path(key).write_text(text, "utf-8")
        return key

    def get_text(self, key: str) -> str | None:
        p = self._root / key.lstrip("/")
        return p.read_text("utf-8") if p.exists() else None

    def exists(self, key: str) -> bool:
        return (self._root / key.lstrip("/")).exists()

    def inbox(self, source_type: str, filename: str) -> str:
        day = dt.date.today().strftime("%Y%m%d")
        return f"kb-raw/inbox/{day}/{source_type}/{filename}"


class MinioObjectStore(FSObjectStore):
    def __init__(self) -> None:
        super().__init__()
        from minio import Minio  # optional dependency
        self._client = Minio(settings.kb_s3_endpoint,
                             access_key=settings.kb_s3_access_key,
                             secret_key=settings.kb_s3_secret_key, secure=False)
        for b in ("kb-raw", "kb-derived"):
            if not self._client.bucket_exists(b):
                self._client.make_bucket(b)

    def put(self, key: str, content: bytes) -> str:
        import io
        bucket, _, obj = key.partition("/")
        self._client.put_object(bucket, obj, io.BytesIO(content), len(content))
        return key


def build_object_store() -> FSObjectStore:
    if settings.kb_s3_endpoint:
        try:
            return MinioObjectStore()
        except Exception:  # pragma: no cover
            return FSObjectStore()
    return FSObjectStore()


object_store = build_object_store()
