from .test_code_projects import setup_project, archive, run
from .test_documents_catalog import context


def program(name, body='           GOBACK.'):
    return f'       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {name}.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 TARGET-NAME PIC X(20).\n       PROCEDURE DIVISION.\n       MAIN-LOGIC.\n{body}\n'.encode()


def add(client, name, library, files, version='v1', tag='业务'):
    import json
    response = client.post('/api/v1/code-projects', files={'file': ('project.zip', archive(files))},
                           data={'project': name, 'library': library, 'version': version, 'tags': json.dumps([tag])})
    assert response.status_code == 200, response.text
    job = response.json()['data']['job_id']; run(client, job)
    return job


def test_three_projects_two_systems_and_cross_upload_links(context):
    client, sessions, _, _ = context
    source = add(client, '调用工程', 'system-A', {'src/ENTRY.cbl': program('ENTRY',
        "           CALL 'SERVICE-PROG'\n           CALL 'CROSS-SERVICE'\n           CALL TARGET-NAME\n           GOBACK.")}, tag='交易')
    before = client.get('/api/v1/graph/struct', params={'library': 'system-A', 'project': '调用工程', 'view': 'files'}).json()['data']
    assert not any(e.get('props', {}).get('cross_project') for e in before['edges'])
    target = add(client, '服务工程', 'system-A', {'src/SERVICE.cbl': program('SERVICE-PROG'), 'src/DYNAMIC.cbl': program('TARGET-NAME')}, tag='服务')
    other = add(client, '外部工程', 'system-B', {'src/EXTERNAL.cbl': program('CROSS-SERVICE')}, tag='外部')
    # Old uploads do not contain the new reference manifest and must still link.
    from app.db import IngestJob
    with sessions() as db:
        job = db.get(IngestJob, source)
        job.options_json = {k: v for k, v in job.options_json.items() if k not in {'external_references', 'reference_schema'}}
        db.commit()
    catalog = client.get('/api/v1/knowledge/catalog', params={'kb': 'system-A'}).json()['data']
    assert {p['name'] for p in catalog['projects']} == {'调用工程', '服务工程'}
    assert {t['value'] for t in catalog['tags']} == {'交易', '服务'}
    scoped = client.get('/api/v1/knowledge/catalog', params={'kb': 'system-A', 'project': '调用工程'}).json()['data']
    assert [t['value'] for t in scoped['tags']] == ['交易']
    files = client.get('/api/v1/knowledge/docs', params={'kb': 'system-A', 'project': '调用工程', 'tag': '交易'}).json()['data']
    assert files['total'] == 1 and files['items'][0]['project_job'] == source
    graph = client.get('/api/v1/graph/struct', params={'library': 'system-A', 'project': '调用工程', 'view': 'files'}).json()['data']
    links = [e for e in graph['edges'] if e.get('props', {}).get('cross_project')]
    assert len(links) == 1 and links[0]['props']['symbol'] == 'SERVICE-PROG'
    assert links[0]['props']['source_job'] == source and links[0]['props']['target_job'] == target
    assert 'CALL' in links[0]['props']['evidence']
    assert all(n['label'] == 'CodeFile' for n in graph['nodes'])
    assert {n['props']['project'] for n in graph['nodes']} == {'调用工程', '服务工程'}
    full = client.get('/api/v1/graph/struct', params={'library': 'system-A', 'project': '调用工程', 'view': 'files', 'cross_system': True}).json()['data']
    assert any(e.get('props', {}).get('target_job') == other for e in full['edges'])
    assert not any(e.get('props', {}).get('symbol') == 'TARGET-NAME' for e in full['edges'])
    # Uploading a replacement target automatically removes links to its old snapshot.
    replacement = add(client, '服务工程', 'system-A', {'src/CHANGED.cbl': program('OTHER-SERVICE')}, version='v2', tag='服务')
    changed = client.get('/api/v1/graph/struct', params={'library': 'system-A', 'project': '调用工程', 'view': 'files'}).json()['data']
    assert not any(e.get('props', {}).get('target_job') == target for e in changed['edges'])


def test_ambiguous_definitions_and_copybook_links(context):
    client, sessions, _, _ = context
    caller = program('COPY-CLIENT').replace(b'       01 TARGET-NAME PIC X(20).', b'       COPY SHARED-RECORD.')
    source = add(client, '引用工程', 'system-A', {'src/ENTRY.cbl': caller})
    first = add(client, '公共定义', 'system-A', {'copy/SHARED-RECORD.cpy': b'       01 SHARED-RECORD.\n          05 CODE PIC X.\n'})
    graph = client.get('/api/v1/graph/struct', params={'library': 'system-A', 'project': '引用工程', 'view': 'files'}).json()['data']
    assert any(e['rel'] == 'IMPORTS' and e.get('props', {}).get('cross_project') for e in graph['edges'])
    add(client, '重名定义', 'system-A', {'copy/SHARED-RECORD.cpy': b'       01 SHARED-RECORD.\n          05 OTHER PIC X.\n'})
    ambiguous = client.get('/api/v1/graph/struct', params={'library': 'system-A', 'project': '引用工程', 'view': 'files'}).json()['data']
    assert not any(e.get('props', {}).get('cross_project') for e in ambiguous['edges'])


def test_file_overview_preserves_intra_project_copy_dependencies(context):
    client, sessions, _, _ = context
    caller = program('COPY-CLIENT').replace(b'       01 TARGET-NAME PIC X(20).', b'       COPY SHARED-RECORD.')
    add(client, '完整工程', 'system-A', {'src/ENTRY.cbl': caller,
        'copy/SHARED-RECORD.cpy': b'       01 SHARED-RECORD.\n          05 ACCOUNT-CODE PIC X.\n'})
    graph = client.get('/api/v1/graph/struct', params={'library': 'system-A', 'view': 'files'}).json()['data']
    nodes = {n['id']: n for n in graph['nodes']}
    assert any(e['rel'] == 'IMPORTS' and nodes[e['src']]['props']['path'] == 'src/ENTRY.cbl'
               and nodes[e['dst']]['props']['path'] == 'copy/SHARED-RECORD.cpy' for e in graph['edges'])
