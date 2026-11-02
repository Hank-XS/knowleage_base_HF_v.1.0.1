import io

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import pytest

from app.ingest.documents import extract_document
from app.knowledge import catalog, document_service, manage
from app.routers import knowledge, misc
from app.stores.objects import FSObjectStore
from .test_code_projects import setup_project, upload, run


def docx_bytes(text='Account design'):
    doc = Document()
    doc.add_heading('System design', 1)
    doc.add_paragraph(text)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = 'Field'
    table.cell(0, 1).text = 'Meaning'
    table.cell(1, 0).text = 'ACCOUNT'
    table.cell(1, 1).text = 'Account number'
    doc.add_paragraph('After the table')
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def pdf_bytes(text=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if text:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_markdown_preserves_tables_fences_and_long_paragraphs():
    long = '完整段落' * 700
    code = '```cobol\n# not a heading\n' + '       CONTINUE\n' * 150 + '```'
    table = '| Field | Meaning |\n| --- | --- |\n' + '| A | B |\n' * 250
    text = f'# 标题\n\n{long}\n\n{code}\n\n{table}\n\n## 后续\n\n重复正文\n\n重复正文\n'
    parsed = extract_document('guide.md', text.encode())
    chunks = parsed['chunks']
    assert any(long in c['text'] for c in chunks)
    assert any(c['text'] == code for c in chunks)
    assert any(c['text'] == table.strip() for c in chunks)
    assert all('not a heading' not in c['title'] for c in chunks)
    for chunk in chunks:
        assert parsed['content'][chunk['start_offset']:chunk['end_offset']] == chunk['text']
    assert sum(c['text'].count('重复正文') for c in chunks) == 2


def test_docx_keeps_document_order_and_table():
    parsed = extract_document('design.docx', docx_bytes())
    text = parsed['content']
    assert text.index('Account design') < text.index('| Field') < text.index('After the table')
    assert any(c['meta_json']['kind'] == 'table' and 'ACCOUNT' in c['text'] for c in parsed['chunks'])
    assert all(c['meta_json']['heading'] == 'System design' for c in parsed['chunks'])


def test_pdf_page_locations_and_scan_rejection():
    parsed = extract_document('guide.pdf', pdf_bytes('Account design'))
    assert 'Account design' in parsed['content']
    assert parsed['chunks'][0]['meta_json']['page_start'] == 1
    with pytest.raises(ValueError, match='OCR'):
        extract_document('scan.pdf', pdf_bytes())
    for name in ('old.doc', 'script.cbl', 'data.txt'):
        with pytest.raises(ValueError, match='仅支持'):
            extract_document(name, b'unsupported')


@pytest.fixture
def context(setup_project, monkeypatch, tmp_path):
    client, sessions, graph, vectors = setup_project
    import app.db as db
    import app.deps as deps
    monkeypatch.setattr(db, 'SessionLocal', sessions)
    monkeypatch.setattr(deps, 'SessionLocal', sessions)
    for module in (document_service, manage, catalog):
        monkeypatch.setattr(module, 'SessionLocal', sessions)
    store = FSObjectStore()
    store._root = tmp_path / 'objects'
    import app.stores.objects as objects
    monkeypatch.setattr(objects, 'object_store', store)
    from app.ingest import code_project
    monkeypatch.setattr(code_project, 'object_store', store)
    monkeypatch.setattr(document_service, 'object_store', store)
    monkeypatch.setattr(document_service, 'graph_store', graph)
    monkeypatch.setattr(document_service, 'vector_store', vectors)
    monkeypatch.setattr(misc, 'graph_store', graph)
    import app.stores.graph as graph_module
    import app.stores.vector as vector_module
    monkeypatch.setattr(graph_module, 'graph_store', graph)
    monkeypatch.setattr(vector_module, 'vector_store', vectors)
    from app.qa import source_view
    monkeypatch.setattr(source_view, 'object_store', store)
    return client, sessions, graph, vectors


def test_document_metadata_version_original_and_statistics(context):
    client, sessions, graph, vectors = context
    def send(version, body, project='Accounts', tags='[" 账户 ", "账户", "API"]'):
        return client.post('/api/v1/knowledge/upload',
                           files={'file': ('design.docx', body)},
                           data={'library_key': 'core', 'project': project, 'version': version,
                                 'purpose': 'design', 'tags': tags})
    original = docx_bytes('Version one')
    first = send('v1', original).json()['data']
    assert first['tags'] == ['账户', 'API']
    second = send('v2', docx_bytes('Version two')).json()['data']
    assert first['id'] == second['id']
    assert send('v1', original, 'Payments').json()['data']['id'] != first['id']
    old = client.get(f'/api/v1/knowledge/docs/{first["id"]}/original', params={'version': 'v1'})
    assert old.status_code == 200 and old.content == original
    old_chunks = client.get(f'/api/v1/knowledge/docs/{first["id"]}/chunks', params={'version': 'v1'}).json()['data']
    assert 'Version one' in old_chunks['content']
    active = [v for v in vectors._data['kb_doc_chunk'] if v['meta'].get('doc_id') == first['id']]
    assert all(v['meta']['version'] == 'v2' for v in active)
    assets = client.get('/api/v1/knowledge/assets', params={'kb': 'core', 'project': 'Accounts', 'tag': '账户'}).json()['data']
    assert assets['total'] == 1 and assets['items'][0]['version'] == 'v2'
    assert assets['stats']['documents'] == 1
    assert assets['stats']['chunks'] == second['chunk_count']
    assert client.get('/api/v1/knowledge/docs', params={'tag': '账'}).json()['data']['total'] == 0
    assert client.get('/api/v1/knowledge/docs', params={'tag': '账户'}).json()['data']['total'] == 2
    from app.qa.source_view import preview_source
    preview = preview_source(path=second['sourcePath'])
    assert preview['available'] and 'Version two' in preview['content']
    assert 'PK' != preview['content'][:2]
    bad = client.post('/api/v1/knowledge/upload', files={'file': ('bad.txt', b'no')}, data={'version': 'v1', 'library_key': 'core'})
    assert bad.status_code == 400
    missing = client.post('/api/v1/knowledge/upload', files={'file': ('x.md', b'# Data')}, data={'version': 'v1'})
    assert missing.status_code == 400
    invalid = client.post('/api/v1/knowledge/upload', files={'file': ('x.md', b'# Data')},
                          data={'version': 'v1', 'library_key': 'core', 'tags': '{"bad": 1}'})
    assert invalid.status_code == 400
    assert client.post('/api/v1/knowledge/libraries', json={'key': 'unique', 'title': 'Accounts'}).status_code == 200
    assert client.post('/api/v1/knowledge/libraries', json={'key': 'another', 'title': ' accounts '}).status_code == 400
    generated = client.post('/api/v1/knowledge/libraries', json={'title': 'Payments'}).json()['data']
    assert generated['key'].startswith('sys-')


def test_project_catalog_latest_and_graph_classification(context, monkeypatch):
    client, sessions, graph, vectors = context
    first = upload(client, version='v1'); run(client, first)
    second = upload(client, version='v2'); run(client, second)
    listing = client.get('/api/v1/knowledge/assets').json()['data']
    assert listing['stats']['projects'] == 1
    assert listing['items'][0]['id'] == second
    assert listing['items'][0]['file_count'] == 3
    assert client.get('/api/v1/knowledge/assets', params={'history': True}).json()['data']['total'] == 2
    docs = client.get('/api/v1/knowledge/docs', params={'project': 'Test project'}).json()['data']
    assert docs['total'] == 3
    assert all(d['project_job'] == second for d in docs['items'])
    current = client.get('/api/v1/graph/struct', params={'library': 'test', 'project': 'Test project'}).json()['data']
    assert current['nodes'] and all(n['props']['project_job'] == second for n in current['nodes'])
    previous = client.get('/api/v1/graph/struct', params={'library': 'test', 'project': 'Test project', 'version': 'v1'}).json()['data']
    assert previous['nodes'] and all(n['props']['project_job'] == first for n in previous['nodes'])
    # Simulate project files saved before classification columns existed.
    import app.db as database
    monkeypatch.setattr(database, 'engine', sessions.kw['bind'])
    with sessions() as db:
        db.query(database.KbDocument).update({'asset_type': 'document', 'project': '', 'project_job': '',
                                             'purpose': 'reference', 'is_current': 1})
        db.commit()
    database.init_db()
    restored = client.get('/api/v1/knowledge/docs', params={'project': 'Test project'}).json()['data']
    assert restored['total'] == 3
    assert all(d['asset_type'] == 'code' and d['project_job'] == second for d in restored['items'])
    for node in graph.dump()['nodes']:
        node['props'].pop('library', None)
        node['props'].pop('tags', None)
    restored_graph = client.get('/api/v1/graph/struct', params={'library': 'test'}).json()['data']
    assert restored_graph['nodes'] and all(n['props']['library'] == 'test' for n in restored_graph['nodes'])
    from app.db import IngestJob
    failed = upload(client, version='v3')
    with sessions() as db:
        job = db.get(IngestJob, failed)
        job.status, job.error = 'failed', 'Parser unavailable'
        db.commit()
    listing = client.get('/api/v1/knowledge/assets').json()['data']
    assert listing['total'] == 1 and listing['items'][0]['id'] == second
    assert listing['items'][0]['attempt_status'] == 'failed'
    assert listing['items'][0]['attempt_version'] == 'v3'


def test_document_failed_publication_retains_successful_version(context, monkeypatch):
    _, sessions, graph, vectors = context
    original = document_service.upload_document(filename='design.md', content=b'# One\n\nValid original',
                                                library_key='core', version='v1')
    before_graph = graph.dump()
    before_vectors = list(vectors._data['kb_doc_chunk'])
    save = vectors.save
    attempts = 0
    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError('Persistence unavailable')
        save()
    monkeypatch.setattr(vectors, 'save', fail_once)
    with pytest.raises(OSError, match='Persistence unavailable'):
        document_service.upload_document(filename='design.md', content=b'# Two\n\nNew data',
                                         library_key='core', version='v2')
    from app.db import KbDocument, KbDocVersion
    with sessions() as db:
        assert db.get(KbDocument, original['id']).version == 'v1'
        assert db.query(KbDocVersion).filter_by(doc_id=original['id'], version='v2').count() == 0
    assert graph.dump() == before_graph
    assert vectors._data['kb_doc_chunk'] == before_vectors
