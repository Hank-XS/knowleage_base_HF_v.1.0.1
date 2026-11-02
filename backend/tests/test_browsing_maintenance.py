from sqlalchemy import select
import pytest

from app.db import KbDocument, KbDocVersion, KbDocChunk
from .test_code_projects import setup_project, upload, run
from .test_documents_catalog import context
from .code_project_sample import sample_files


def file_id(sessions, job, suffix='src/MAIN.cbl'):
    with sessions() as db:
        return db.scalar(select(KbDocument.id).where(KbDocument.project_job == job,
                         KbDocument.source_path.endswith('/' + suffix)))


def test_real_versions_cross_snapshots_and_insert_alignment(context, monkeypatch):
    client, sessions, _, _ = context
    first = upload(client, version='v1'); run(client, first)
    files = sample_files()
    files['src/MAIN.cbl'] = files['src/MAIN.cbl'].replace(b'       DATA DIVISION.', b'      * Added in v2\n       DATA DIVISION.')
    second = upload(client, files=files, version='v2'); run(client, second)
    current = file_id(sessions, second)
    before = client.get(f'/api/v1/knowledge/docs/{current}/versions').json()['data']
    versions = client.get(f'/api/v1/knowledge/docs/{current}/comparison-versions').json()['data']
    assert [v['version'] for v in versions] == ['v1', 'v2']
    result = client.get(f'/api/v1/knowledge/docs/{current}/comparison',
                        params={'old': versions[0]['id'], 'new': versions[1]['id']}).json()['data']
    assert result['stats'] == {'added': 1, 'removed': 0, 'modified': 0}
    assert before == client.get(f'/api/v1/knowledge/docs/{current}/versions').json()['data']
    client.post(f'/api/v1/knowledge/docs/{current}/versions', json={'new_version': 'v2-diff', 'note': '自动生成对比版本'})
    import app.db as database
    monkeypatch.setattr(database, 'engine', sessions.kw['bind'])
    database.init_db()
    assert client.get(f'/api/v1/knowledge/docs/{current}').json()['data']['version'] == 'v2'
    assert len(client.get(f'/api/v1/knowledge/docs/{current}/comparison-versions').json()['data']) == 2
    with sessions() as db:
        assert db.scalar(select(KbDocVersion.id).where(KbDocVersion.doc_id == current, KbDocVersion.version == 'v2-diff'))
    other = file_id(sessions, second, 'src/CHECK.cbl')
    foreign = client.get(f'/api/v1/knowledge/docs/{other}/comparison-versions').json()['data'][0]['id']
    assert client.get(f'/api/v1/knowledge/docs/{current}/comparison', params={'old': foreign, 'new': versions[1]['id']}).status_code == 400


def test_file_graph_keeps_real_cross_file_edges(context):
    client, sessions, graph, _ = context
    job = upload(client); run(client, job)
    main = file_id(sessions, job)
    own = client.get('/api/v1/graph/struct', params={'doc_id': main, 'detail': True, 'neighbors': False}).json()['data']
    assert own['nodes'] and all(n['props']['path'] == 'src/MAIN.cbl' for n in own['nodes'])
    assert {'Program', 'Procedure'} <= {n['label'] for n in own['nodes']}
    related = client.get('/api/v1/graph/struct', params={'doc_id': main, 'detail': True, 'neighbors': True}).json()['data']
    assert any(n['external'] for n in related['nodes'])
    assert any(e['rel'] == 'CALLS' for e in related['edges'])
    assert len(related['nodes']) > len(own['nodes'])


def test_bidirectional_references_stay_in_project_and_library(context):
    client, sessions, _, _ = context
    job = upload(client); run(client, job)
    def doc(name, library='test', project='Test project', text='MAIN-PROGRAM calls CHECK-CUSTOMER.'):
        r = client.post('/api/v1/knowledge/upload', files={'file': (name, ('# Design\n\n' + text).encode())},
                        data={'library_key': library, 'project': project, 'version': 'v1'})
        assert r.status_code == 200, r.text
        return r.json()['data']['id']
    attached = doc('attached.md')
    general = doc('general.md', project='')
    doc('other-project.md', project='Another project')
    doc('other-system.md', library='another')
    doc('substring.md', text='MAIN-PROGRAM-OTHER')
    main = file_id(sessions, job)
    related = client.get(f'/api/v1/knowledge/codemap/{main}').json()['data']['relatedDocs']
    assert {r['id'] for r in related} == {attached, general}
    reverse = client.get(f'/api/v1/knowledge/codemap/{attached}', params={'direction': 'doc2code'}).json()['data']
    assert len(reverse['relatedDocs']) == 2
    assert {r['name'] for r in reverse['relatedDocs']} == {'Test project/src/MAIN.cbl', 'Test project/src/CHECK.cbl'}
    filtered = client.get('/api/v1/knowledge/docs', params={'kb': 'test', 'project': 'Test project', 'asset_type': 'code'}).json()['data']
    assert filtered['total'] == 3


def clean(client, scope):
    preview = client.post('/api/v1/knowledge/cleanup/preview', json=scope)
    assert preview.status_code == 200, preview.text
    p = preview.json()['data']
    result = client.post('/api/v1/knowledge/cleanup/execute', json={**scope, 'confirmation_token': p['token']})
    assert result.status_code == 200, result.text
    return p


def test_cleanup_is_scoped_and_all_views_agree(context):
    client, sessions, graph, vectors = context
    first = upload(client, version='v1'); run(client, first)
    second = upload(client, version='v2'); run(client, second)
    doc = file_id(sessions, second)
    source_before = client.get(f'/api/v1/knowledge/docs/{doc}').json()['data']['content']
    chunks = client.get(f'/api/v1/knowledge/docs/{doc}/chunks').json()['data']['chunks']
    scope = {'target': 'chunks', 'doc_id': doc, 'version': 'v2', 'chunk_ids': [chunks[0]['id']]}
    stale = client.post('/api/v1/knowledge/cleanup/preview', json=scope).json()['data']
    p = clean(client, scope)
    assert p['counts']['chunks'] == p['counts']['vectors'] == 1
    assert client.post('/api/v1/knowledge/cleanup/execute', json={**scope, 'confirmation_token': stale['token']}).status_code == 400
    assert len(client.get(f'/api/v1/knowledge/docs/{doc}/chunks').json()['data']['chunks']) == len(chunks) - 1
    legacy = client.get(f'/api/v1/code-projects/{second}/chunks', params={'path': 'src/MAIN.cbl'}).json()['data']
    assert legacy['total'] == len(chunks) - 1
    assert client.post('/api/v1/knowledge/cleanup/preview', json={'target': 'graph'}).status_code == 400
    other_nodes = {n['id'] for n in graph.dump()['nodes'] if n['props'].get('project_job') == second and n['props'].get('path') != 'src/MAIN.cbl'}
    count_first = len(graph.find(project_job=first))
    p = clean(client, {'target': 'graph', 'doc_id': doc})
    assert p['counts']['nodes'] > 0
    assert other_nodes <= {n['id'] for n in graph.dump()['nodes']}
    assert len(graph.find(project_job=first)) == count_first
    assert client.get('/api/v1/graph/struct', params={'doc_id': doc, 'detail': True}).json()['data']['nodes'] == []
    assert not any(n['props']['path'] == 'src/MAIN.cbl' for n in client.get(f'/api/v1/code-projects/{second}/graph').json()['data']['nodes'])
    assert client.get(f'/api/v1/knowledge/docs/{doc}').json()['data']['content'] == source_before
    clean(client, {'target': 'chunks', 'job_id': second})
    assert client.get('/api/v1/knowledge/assets').json()['data']['stats']['chunks'] == 0
    assert not any(v['meta'].get('project_job') == second for v in vectors._data['kb_code_chunk'])
    assert any(v['meta'].get('project_job') == first for v in vectors._data['kb_code_chunk'])


def test_cleanup_requires_confirmation_and_recovers_on_save_failure(context, monkeypatch):
    client, sessions, graph, vectors = context
    job = upload(client); run(client, job)
    scope = {'target': 'graph', 'job_id': job}
    assert client.post('/api/v1/knowledge/cleanup/execute', json=scope).status_code == 400
    from app.knowledge import maintenance
    p = maintenance.preview(scope)
    count = len(graph.find(project_job=job))
    original, attempts = graph.save, 0
    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError('Disk unavailable')
        original()
    monkeypatch.setattr(graph, 'save', fail_once)
    with pytest.raises(OSError, match='Disk unavailable'):
        maintenance.execute(scope, p['token'])
    assert len(graph.find(project_job=job)) == count
