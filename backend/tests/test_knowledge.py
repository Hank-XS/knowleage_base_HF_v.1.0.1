"""知识库管理 API：同步 / 列表 / 上传 / 切片 / 版本对比 / 代码映射。"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("KB_LLM_API_KEY", "")
_repo = Path(__file__).resolve().parents[2]
if (_repo / "hf_data").exists():
    os.environ["KB_DATASET_ROOT"] = str(_repo / "hf_data")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.deps import hash_password, issue_token  # noqa: E402
from app.db import SessionLocal, User  # noqa: E402
from app.main import app  # noqa: E402
from app.knowledge import manage as km  # noqa: E402

init_db()


def _token(role: str = "admin") -> str:
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == "admin").one_or_none()
        if u is None:
            from app.seed import seed_users
            seed_users()
            u = db.query(User).filter(User.username == "admin").one()
        # ensure role
        u.role = role
        db.commit()
        db.refresh(u)
        return issue_token(u)


def _client() -> TestClient:
    return TestClient(app)


def test_sync_and_libraries():
    result = km.sync_from_dataset(force=True)
    assert result.get("synced") is True
    assert result.get("docs", 0) > 10

    tree = km.library_tree()
    assert isinstance(tree, list) and len(tree) >= 1
    assert any(n.get("count", 0) > 0 for n in tree)


def test_api_docs_list_and_detail():
    km.sync_from_dataset(force=False)
    c = _client()
    h = {"Authorization": f"Bearer {_token()}"}

    r = c.get("/api/v1/knowledge/libraries", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert len(body["data"]) >= 1

    r = c.get("/api/v1/knowledge/docs", headers=h, params={"page": 1, "page_size": 5})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] >= 5
    assert len(data["items"]) >= 1
    doc_id = data["items"][0]["id"]

    r = c.get(f"/api/v1/knowledge/docs/{doc_id}", headers=h)
    assert r.status_code == 200
    detail = r.json()["data"]
    assert detail["id"] == doc_id
    assert "content" in detail


def test_upload_chunk_diff_codemap():
    km.sync_from_dataset(force=False)
    c = _client()
    h = {"Authorization": f"Bearer {_token()}"}

    content = b"# Upload Demo\n\n## Section A\n\nhello knowledge\n\n## Section B\n\nworld\n"
    files = {"file": ("upload_demo.md", content, "text/markdown")}
    form = {
        "library_key": "01_tech_docs",
        "version": "v1.0",
        "security": "public",
        "author": "admin",
        "tags": '["SWIFT"]',
        "official": "true",
        "auto_chunk": "true",
    }
    r = c.post("/api/v1/knowledge/upload", headers=h, files=files, data=form)
    assert r.status_code == 200, r.text
    doc = r.json()["data"]
    doc_id = doc["id"]
    assert doc["name"] == "upload_demo"
    assert doc["vectorized"] is True

    r = c.get(f"/api/v1/knowledge/docs/{doc_id}/chunks", headers=h)
    assert r.status_code == 200
    chunks = r.json()["data"]["chunks"]
    assert len(chunks) >= 1

    # 增加版本用于 diff
    r = c.post(
        f"/api/v1/knowledge/docs/{doc_id}/versions",
        headers=h,
        json={"new_version": "v1.1", "note": "补充说明一行"},
    )
    assert r.status_code == 200, r.text

    r = c.get(
        f"/api/v1/knowledge/docs/{doc_id}/diff",
        headers=h,
        params={"old": "v1.0", "new": "v1.1"},
    )
    assert r.status_code == 200
    diff = r.json()["data"]
    assert diff["stats"]["added"] + diff["stats"]["modified"] >= 1

    r = c.get("/api/v1/knowledge/codemap", headers=h)
    assert r.status_code == 200
    files_list = r.json()["data"]
    assert isinstance(files_list, list)
    if files_list:
        code_id = files_list[0]["key"]
        r = c.get(f"/api/v1/knowledge/codemap/{code_id}", headers=h)
        assert r.status_code == 200
        mapped = r.json()["data"]
        assert "file" in mapped
        assert "relatedDocs" in mapped


def test_batch_status():
    km.sync_from_dataset(force=False)
    c = _client()
    h = {"Authorization": f"Bearer {_token()}"}
    r = c.get("/api/v1/knowledge/docs", headers=h, params={"page_size": 2})
    ids = [x["id"] for x in r.json()["data"]["items"]]
    assert ids
    r = c.post(
        "/api/v1/knowledge/docs/batch-status",
        headers=h,
        json={"doc_ids": ids, "action": "submit", "status": "review"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["updated"] == len(ids)
