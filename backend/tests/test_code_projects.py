"""Real CodeGraph integration; no fake parser. Run with isolated KB_DATA_DIR.

python -m pytest tests/test_code_projects.py -q
"""
import io
import stat
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, IngestJob, KbDocChunk, KbDocument
from app.deps import current_user
from app.ingest import code_project as cp
from app.main import app
from app.routers import code_projects as routes
from app.stores.graph import MemGraphStore
from app.stores.vector import NumpyVectorStore
from .code_project_sample import sample_files


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buffer.getvalue()


@pytest.fixture
def setup_project(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "test.sqlite3"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(cp, 'SessionLocal', sessions)
    monkeypatch.setattr(routes, 'SessionLocal', sessions)
    monkeypatch.setattr(cp, 'object_store', SimpleNamespace(_root=tmp_path / 'objects'))
    graph, vectors = MemGraphStore(), NumpyVectorStore()
    graph._nodes, graph._edges = {}, []
    graph._path = tmp_path / 'graph.json'
    vectors._data = {c: [] for c in vectors._data}
    vectors._path = tmp_path / 'vectors.json'
    monkeypatch.setattr(cp, 'graph_store', graph)
    monkeypatch.setattr(cp, 'vector_store', vectors)
    monkeypatch.setattr(cp, 'submit', lambda _: None)  # Explicit deterministic scheduling in API tests.
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(username='tester', role='admin')
    yield TestClient(app), sessions, graph, vectors
    app.dependency_overrides.clear()
    engine.dispose()


def upload(client, files=None, version='v1', project='Test project'):
    response = client.post('/api/v1/code-projects',
                           files={'file': ('project.zip', archive(files or sample_files()), 'application/zip')},
                           data={'project': project, 'version': version, 'library': 'test'})
    assert response.status_code == 200, response.text
    payload = response.json()['data']
    assert payload['status'] == 'queued'
    return payload['job_id']


def run(client, job_id):
    cp.run_project(job_id)
    response = client.get(f'/api/v1/code-projects/{job_id}')
    assert response.status_code == 200
    payload = response.json()['data']
    assert payload['status'] == 'done', payload
    return payload


def test_real_parser_upload_graph_chunks_source_and_index(setup_project):
    client, sessions, graph, vectors = setup_project
    job_id = upload(client)
    detail = run(client, job_id)
    assert detail['model_used'] is False
    assert detail['summary']['files'] == 3
    assert detail['summary']['chunks'] >= 4
    assert detail['summary']['skipped'] == 1
    assert any(r['name'] == 'MISSING-SERVICE' for r in detail['unresolved'])
    result = client.get(f'/api/v1/code-projects/{job_id}/graph').json()['data']
    nodes = {n['id']: n for n in result['nodes']}
    assert any(e['rel'] == 'CALLS' and nodes[e['dst']]['props']['name'] == 'CHECK-CUSTOMER'
               and nodes[e['src']]['props']['path'] != nodes[e['dst']]['props']['path'] for e in result['edges'])
    assert any(e['rel'] == 'IMPORTS' and nodes[e['dst']]['props']['path'] == 'copybooks/CUSTOMER.cpy'
               for e in result['edges'])
    chunks = client.get(f'/api/v1/code-projects/{job_id}/chunks').json()['data']['items']
    for chunk in chunks:
        source = client.get(f'/api/v1/code-projects/{job_id}/source', params={'path': chunk['path']}).json()['data']['content']
        assert chunk['text'] == ''.join(source.splitlines(keepends=True)[chunk['start_line']-1:chunk['end_line']])
    with sessions() as db:
        assert len(db.scalars(select(KbDocument)).all()) == 3
        assert len(db.scalars(select(KbDocChunk)).all()) == len(chunks)
    assert len(graph.find(project_job=job_id)) == detail['summary']['nodes']
    assert vectors.count('kb_code_chunk') == len(chunks)
    assert all(f'projects/{job_id}/source/' in c['meta']['source_path'] for c in vectors._data['kb_code_chunk'])
    assert client.get(f'/api/v1/code-projects/{job_id}/source', params={'path': '../../.env'}).status_code == 404
    assert client.get('/api/v1/code-projects/not-a-job/graph').status_code == 404


def test_long_structures_stay_whole_and_file_fallback_stays_bounded(setup_project):
    client, sessions, _, vectors = setup_project
    lines = [
        '       IDENTIFICATION DIVISION.',
        '       PROGRAM-ID. LONG-PROGRAM.',
        '       DATA DIVISION.',
        '       WORKING-STORAGE SECTION.',
        '       01 LONG-RECORD.',
        *[f'          05 ITEM-{i:03d} PIC X.' for i in range(110)],
        '       PROCEDURE DIVISION.',
        '       PROCESS-SECTION SECTION.',
        '       LONG-PARAGRAPH.',
        *["           DISPLAY 'ROW'" for _ in range(138)],
        "           DISPLAY 'ROW'.",
        '       SHORT-PARAGRAPH.',
        '           GOBACK.',
        '       NEXT-SECTION SECTION.',
        '       EXIT-PARAGRAPH.',
        '           GOBACK.',
    ]
    source = '\n'.join(lines) + '\n'
    job_id = upload(client, {
        'src/LONG.cbl': source.encode('utf-8'),
        'src/NOTES.cbl': b'      * No structural unit in this file.\n' * 205,
    })
    detail = run(client, job_id)
    chunks = client.get(f'/api/v1/code-projects/{job_id}/chunks',
                        params={'page_size': 100}).json()['data']['items']
    nodes = client.get(f'/api/v1/code-projects/{job_id}/graph').json()['data']['nodes']
    structural = [c for c in chunks if c['node_id']]
    for title in ('LONG-PARAGRAPH', 'PROCESS-SECTION', 'LONG-RECORD'):
        matching = [c for c in structural if c['title'] == title]
        assert len(matching) == 1, f'{title} must remain a single complete chunk'
        assert matching[0]['end_line'] - matching[0]['start_line'] + 1 > 100
    paragraph = next(c for c in structural if c['title'] == 'LONG-PARAGRAPH')
    assert paragraph['start_line'] == lines.index('       LONG-PARAGRAPH.') + 1
    assert paragraph['end_line'] == lines.index('       SHORT-PARAGRAPH.')
    assert paragraph['end_line'] - paragraph['start_line'] + 1 == 140

    by_id = {n['id']: n['props'] for n in nodes}
    source_lines = source.splitlines(keepends=True)
    for chunk in structural:
        node = by_id[chunk['node_id']]
        assert sum(c['node_id'] == chunk['node_id'] for c in structural) == 1
        assert (chunk['start_line'], chunk['end_line']) == (node['start_line'], node['end_line'])
        expected = ''.join(source_lines[chunk['start_line'] - 1:chunk['end_line']])
        assert chunk['text'] == expected
        assert source[chunk['start_offset']:chunk['end_offset']] == expected

    fallback = [c for c in chunks if c['path'] == 'src/NOTES.cbl']
    assert [(c['start_line'], c['end_line']) for c in fallback] == [(1, 100), (101, 200), (201, 205)]
    assert all(c['node_id'] == '' for c in fallback)
    assert not next(f for f in detail['files'] if f['path'] == 'src/NOTES.cbl')['structural_chunks']
    with sessions() as db:
        assert db.get(KbDocChunk, paragraph['id']).text == paragraph['text']
    assert next(c for c in vectors._data['kb_code_chunk']
                if c['id'] == paragraph['id'])['meta']['text'] == paragraph['text']


def test_reupload_replaces_only_same_project_version(setup_project):
    client, sessions, graph, vectors = setup_project
    first = upload(client)
    run(client, first)
    v2 = upload(client, version='v2')
    run(client, v2)
    files = sample_files()
    del files['src/CHECK.cbl']
    replacement = upload(client, files)
    detail = run(client, replacement)
    assert any(r['name'] == 'CHECK-CUSTOMER' for r in detail['unresolved'])
    assert not graph.find(project_job=first)
    assert graph.find(project_job=v2)
    assert graph.find(project_job=replacement)
    assert all(c['meta']['project_job'] != first for c in vectors._data['kb_code_chunk'])
    assert client.get(f'/api/v1/code-projects/{first}').json()['data']['superseded_by'] == replacement
    # Historical result is still readable, but no longer returned by global retrieval.
    assert client.get(f'/api/v1/code-projects/{first}/chunks').json()['data']['total'] > 0
    with sessions() as db:
        assert all(d.status == 'archived' for d in db.scalars(select(KbDocument).where(
            KbDocument.source_path.startswith(f'kb-raw/projects/{first}/'))))


def test_parser_failure_preserves_previous_and_retry_creates_snapshot(setup_project, monkeypatch):
    client, sessions, graph, vectors = setup_project
    first = upload(client)
    run(client, first)
    failed = upload(client)
    original = cp.run_codegraph
    def broken(_):
        raise ValueError('simulated parser failure')
    monkeypatch.setattr(cp, 'run_codegraph', broken)
    cp.run_project(failed)
    detail = client.get(f'/api/v1/code-projects/{failed}').json()['data']
    assert detail['status'] == 'failed'
    assert 'simulated parser failure' in detail['error']
    assert graph.find(project_job=first)
    assert not graph.find(project_job=failed)
    assert client.get(f'/api/v1/code-projects/{failed}/graph').status_code == 409
    monkeypatch.setattr(cp, 'run_codegraph', original)
    response = client.post(f'/api/v1/code-projects/{failed}/retry')
    assert response.status_code == 200
    retried = response.json()['data']['job_id']
    assert retried != failed
    run(client, retried)
    assert client.post(f'/api/v1/code-projects/{retried}/retry').status_code == 409


def test_publish_failure_restores_previous_snapshot(setup_project, monkeypatch):
    client, sessions, graph, vectors = setup_project
    first = upload(client)
    run(client, first)
    replacement = upload(client)
    original_save = vectors.save
    calls = 0
    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError('simulated persistence failure')
        original_save()
    monkeypatch.setattr(vectors, 'save', fail_once)
    cp.run_project(replacement)
    assert client.get(f'/api/v1/code-projects/{replacement}').json()['data']['status'] == 'failed'
    assert client.get(f'/api/v1/code-projects/{first}').json()['data']['active'] is True
    assert graph.find(project_job=first)
    assert not graph.find(project_job=replacement)
    assert all(ch['meta']['project_job'] == first for ch in vectors._data['kb_code_chunk'])
    with sessions() as db:
        docs = db.scalars(select(KbDocument)).all()
        assert len(docs) == 3 and all(d.status == 'published' for d in docs)


@pytest.mark.parametrize('name', ['../escape.cbl', '/absolute.cbl', 'C:/absolute.cbl', 'a/../../escape.cbl', 'CON.cbl', 'a.cbl:stream', 'trailing./x.cbl'])
def test_zip_rejects_unsafe_paths(name):
    with pytest.raises(ValueError):
        cp.inspect_archive(archive({name: b'x'}))


def test_archive_encoding_duplicates_symlinks_and_limits(monkeypatch):
    source = '       *> 中文注释\n'.encode('gb18030')
    content = archive({'a.cbl': source})
    with pytest.raises(ValueError, match='编码'):
        cp.inspect_archive(content)
    assert '中文注释' in cp.inspect_archive(content, 'gb18030')[0]['a.cbl']
    with pytest.raises(ValueError, match='重复'):
        cp.inspect_archive(archive({'a.cbl': b'a', 'A.cbl': b'b'}))
    with pytest.raises(ValueError):
        cp.inspect_archive(b'not zip')
    with pytest.raises(ValueError, match='未找到'):
        cp.inspect_archive(archive({'README.md': b'doc'}))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        link = zipfile.ZipInfo('link.cbl')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, '../outside')
    with pytest.raises(ValueError, match='符号链接'):
        cp.inspect_archive(buffer.getvalue())
    monkeypatch.setattr(cp, 'MAX_SOURCE', 8)
    with pytest.raises(ValueError, match='限制'):
        cp.inspect_archive(archive({'big.cbl': b'a' * 9}))


def test_authentication_and_upload_validation(setup_project):
    client, *_ = setup_project
    response = client.post('/api/v1/code-projects', files={'file': ('wrong.txt', b'x')},
                           data={'project': 'P', 'version': 'v1'})
    assert response.status_code == 400
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(username='biz', role='biz')
    response = client.post('/api/v1/code-projects', files={'file': ('p.zip', archive(sample_files()))},
                           data={'project': 'P', 'version': 'v1'})
    assert response.status_code == 403
    app.dependency_overrides.clear()
    assert client.get('/api/v1/code-projects').status_code == 401
