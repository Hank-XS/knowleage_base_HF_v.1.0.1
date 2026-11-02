"""A clean installation stays empty across startup and reads, and still accepts data."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('entrypoint', ['http', 'mcp'])
def test_startup_stays_empty_until_explicit_import(tmp_path, entrypoint):
    dataset = tmp_path / 'dataset' / '02_code_assets'
    dataset.mkdir(parents=True)
    (dataset / 'EXAMPLE.cbl').write_text(
        '       IDENTIFICATION DIVISION.\n       PROGRAM-ID. EXAMPLE.\n'
        '       PROCEDURE DIVISION.\n       MAIN.\n           GOBACK.\n', encoding='utf-8')
    script = '''
import sys
from fastapi.testclient import TestClient
from app.config import settings
from app.db import SessionLocal, KbDocument, KbDocChunk, IngestJob, User
from app.main import app, startup
from app.stores.graph import graph_store
from app.stores.vector import vector_store
assert settings.kb_auto_import is False
if sys.argv[1] == 'mcp':
    from app.mcp_server import _bootstrap
    _bootstrap()
    _bootstrap()
else:
    startup()
    startup()
with TestClient(app) as client:
    login = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'admin123'})
    assert login.status_code == 200, login.text
    headers = {'Authorization': 'Bearer ' + login.json()['data']['token']}
    assert client.get('/api/v1/knowledge/libraries', headers=headers).json()['data'] == []
    assert client.get('/api/v1/knowledge/docs', headers=headers).json()['data']['total'] == 0
    assert graph_store.stats()['nodes'] == 0
    assert graph_store.stats()['edges'] == 0
    assert all(count == 0 for count in vector_store.stats().values())
    with SessionLocal() as db:
        assert db.query(User).count() > 0
        for model in (KbDocument, KbDocChunk, IngestJob):
            assert db.query(model).count() == 0
    imported = client.post('/api/v1/knowledge/sync', headers=headers)
    assert imported.status_code == 200, imported.text
    assert imported.json()['data']['docs'] == 1
    assert client.get('/api/v1/knowledge/docs', headers=headers).json()['data']['total'] == 1
'''
    env = {**os.environ, 'KB_DATA_DIR': str(tmp_path / 'data'),
           'KB_DATASET_ROOT': str(dataset.parent)}
    env.pop('KB_AUTO_IMPORT', None)
    completed = subprocess.run([sys.executable, '-c', script, entrypoint],
                               cwd=Path(__file__).resolve().parents[1], env=env,
                               capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_missing_seed_does_not_create_demo_graph(tmp_path, monkeypatch):
    from app import seed
    from app.stores import graph

    monkeypatch.setattr(graph, 'DATA_DIR', tmp_path)
    store = graph.MemGraphStore()
    monkeypatch.setattr(seed, 'graph_store', store)
    monkeypatch.setattr(seed, 'SEED_DIR', tmp_path / 'missing-seed')
    assert seed.seed_knowledge(force=True)['skipped'] is True
    assert store.stats()['nodes'] == 0
    assert store.stats()['edges'] == 0
