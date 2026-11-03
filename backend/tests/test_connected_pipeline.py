"""Generated fixtures verify the whole upload → relationships → RAG chain and graph pagination."""
import pytest
from sqlalchemy import select
from .test_hybrid_retrieval import retrieval_context, context, setup_project
from .test_cross_projects import add, program
from .test_code_projects import archive, upload, run


def test_caller_evidence_reaches_the_outer_loop(retrieval_context):
    from app.knowledge.retrieval import retrieve
    from app.db import KbDocChunk
    client, sessions, _, _ = retrieval_context
    code = program('LOAD-RUN', '''           PERFORM MAIN-LOOP.
           GOBACK.
       MAIN-LOOP.
           PERFORM UNTIL TARGET-NAME = 'DONE'
               PERFORM DISPATCH-RECORD
           END-PERFORM.
       DISPATCH-RECORD.
           EVALUATE TARGET-NAME
               WHEN OTHER PERFORM HANDLE-UNKNOWN
           END-EVALUATE.
       HANDLE-UNKNOWN.
           DISPLAY 'unknown record'.
       UNRELATED-NOTE.
           DISPLAY 'PERFORM HANDLE-UNKNOWN'.''')
    add(client, 'Synthetic loader', 'loader', {'LOADER.cbl': code})
    with sessions() as db:
        for chunk in db.scalars(select(KbDocChunk)):
            chunk.meta_json = {}  # Older deployments lack kind/start_line/end_line metadata.
        db.commit()
    hits = retrieve('LOAD-RUN 的 HANDLE-UNKNOWN 会直接终止还是继续后续记录？', 'code_understanding', ['LOAD-RUN', 'HANDLE-UNKNOWN'])
    contexts = [e for e in hits if e.get('kind') == 'control_context']
    assert any('EVALUATE TARGET-NAME' in e['text'] for e in contexts)
    assert any("PERFORM UNTIL TARGET-NAME = 'DONE'" in e['text'] for e in contexts)
    assert not any('UNRELATED-NOTE' in e['text'] for e in contexts)


def test_later_upload_links_are_used_by_rag_and_expire_with_versions(retrieval_context):
    from app.knowledge.retrieval import retrieve
    client, _, _, _ = retrieval_context
    add(client, 'Caller project', 'shared', {'CALLER.cbl': program('CALLER-RUN', "           CALL 'REMOTE-WORKER'.\n           GOBACK.")})
    target = add(client, 'Worker project', 'shared', {'SERVICE.cbl': program('REMOTE-WORKER', "           DISPLAY 'worker implementation'.\n           GOBACK.")})
    hits = retrieve('CALLER-RUN 调用的外部程序如何实现？', 'code_understanding', ['CALLER-RUN'])
    assert any(e.get('kind') == 'dependency_context' and target in e['path'] and 'worker implementation' in e['text'] for e in hits)
    add(client, 'Worker project', 'shared', {'SERVICE.cbl': program('OTHER-WORKER')}, version='v2')
    hits = retrieve('CALLER-RUN 调用的外部程序如何实现？', 'code_understanding', ['CALLER-RUN'])
    assert not any(target in (e.get('path') or e.get('obj', '')) for e in hits)


def test_document_mentions_and_code_share_the_relation_snapshot(retrieval_context):
    from app.knowledge.relations import relation_graph
    from app.knowledge.retrieval import retrieve
    client, _, graph, _ = retrieval_context
    response = client.post('/api/v1/knowledge/upload', files={'file': ('guide.md', b'# Worker guide\n\nWORKER-ENTRY implements the daily worker.\n')},
                           data={'version':'v1', 'library_key':'shared', 'project':'Worker project'})
    assert response.status_code == 200, response.text
    # Document is uploaded first. A later code upload must close the reference too.
    add(client, 'Worker project', 'shared', {'WORKER.cbl': program('WORKER-ENTRY')})
    snapshot = relation_graph(graph)
    assert any(e['rel'] == 'MENTIONS' and e['props']['method'] == 'explicit_unique_mention' for e in snapshot.edges)
    hits = retrieve('WORKER-ENTRY 的说明文档是什么？', 'code_understanding', ['WORKER-ENTRY'])
    assert any(e['channel'] == 'doc' and 'daily worker' in e['text'] for e in hits)


def test_upload_quality_preserves_columns_and_reports_quarantined_files(context):
    from app.ingest import code_project as cp
    from app.db import IngestJob, KbDocVersion
    client, sessions, _, _ = context
    body = program('CLEAN-RUN').decode()
    files = {'GOOD.cbl': ('\ufeff' + body.replace('\n', '\r\n')).encode(), 'DUP.cbl': body.encode(),
             'EMPTY.cbl': b'  \n', 'CONFLICT.cbl': b'<<<<<<< local\n       GOBACK.\n>>>>>>> remote\n'}
    job = upload(client, files=files)
    detail = run(client, job)
    assert detail['quality_report']['accepted'] == 2 and detail['quality_report']['quarantined'] == 2
    assert any(q.get('duplicate_of') for q in detail['quality_report']['files'].values())
    with sessions() as db:
        versions = db.scalars(select(KbDocVersion)).all()
        assert all(v.content == body for v in versions)
        assert all(v.meta_json['quality']['sha256'] for v in versions)
    assert (cp.snapshot_root(job) / 'upload.zip').is_file()


def test_corrupt_embedding_batch_never_publishes_a_partial_snapshot(context, monkeypatch):
    from app.ingest import code_project as cp
    from app.db import IngestJob
    client, sessions, graph, _ = context
    old = add(client, 'Worker project', 'shared', {'WORKER.cbl': program('WORKER-ENTRY')})
    class BrokenEmbedder:
        name = 'broken'
        def embed(self, texts):
            return []
    monkeypatch.setattr(cp, 'get_embedder', lambda: BrokenEmbedder())
    response = client.post('/api/v1/code-projects', files={'file': ('x.zip', archive({'NEXT.cbl':program('NEXT-ENTRY')}))},
                           data={'project':'Worker project','library':'shared','version':'v2'})
    new = response.json()['data']['job_id']; cp.run_project(new)
    with sessions() as db:
        assert db.get(IngestJob, new).status == 'failed'
        assert db.get(IngestJob, old).options_json['active']
    assert not any(n['props'].get('project_job') == new for n in graph.dump()['nodes'])


def test_pagination_returns_every_node_and_edge_and_snapshot_cache_invalidates(context):
    from app.knowledge.graph_view import build_graph
    from app.knowledge.relations import relation_graph
    _, _, graph, _ = context
    for n in range(650):
        graph.upsert_node(f'file/{n}', 'CodeFile', dict(name=f'file{n}', library='synthetic', path=f'{n}.cbl'))
        if n:
            graph.upsert_edge(f'file/{n-1}', 'CALLS', f'file/{n}')
    first = relation_graph(graph)
    assert relation_graph(graph) is first
    nodes, edges, offset = [], [], 0
    while offset is not None:
        page = build_graph(graph, library='synthetic', view='files', limit=100, offset=offset)
        nodes.extend(page['nodes']); edges.extend(page['edges']); offset = page['pagination']['next_offset']
    assert len(nodes) == len({n['id'] for n in nodes}) == 650
    assert len(edges) == 649 and not page['truncated']
    assert {e['src'] for e in edges} <= {n['id'] for n in nodes}
    graph.upsert_node('file/0', 'CodeFile', {'name':'updated'})
    assert relation_graph(graph) is not first


def test_document_quality_checks_reject_bad_text_and_keep_duplicate_locations():
    from app.ingest.documents import extract_document
    with pytest.raises(ValueError, match='控制'):
        extract_document('bad.md', b'# Data\n\x00binary')
    result = extract_document('normal.md', b'# First\n\nSame text\n\n# Second\n\nSame text\n')
    assert result['content'].count('Same text') == 2
    assert result['quality']['sha256']


def test_caller_passages_survive_tool_transport_with_correct_locations():
    from app.tools.handlers import _trim_evidence
    from app.knowledge.passage import bounded
    text = ''.join(' ' * 7 + f'LINE-{n:03d}' + ' ' * 65 + '\n' for n in range(70))
    evidence = dict(channel='code', text=text, loc='L100-L169', ref='caller')
    result = _trim_evidence([evidence])[0]
    assert 'LINE-069' in result['snippet'] and result['loc'] == 'L100-L169'
    short = bounded(evidence, max_chars=500)
    assert short['content_truncated'] and short['loc'] == 'L100-L105'


def test_same_project_duplicate_program_ids_require_a_precise_file(retrieval_context):
    from app.knowledge.retrieval import vector_evidence
    client, _, _, _ = retrieval_context
    add(client, 'Duplicate project', 'dup', {'one/ENTRY.cbl': program('SAME-ENTRY'), 'two/ENTRY.cbl':program('SAME-ENTRY')})
    hits = vector_evidence('SAME-ENTRY 做什么？', ['kb_code_chunk'], 5)
    assert hits and all(e['kind'] == 'ambiguous_scope' for e in hits)
    precise = vector_evidence('one/ENTRY.cbl 做什么？', ['kb_code_chunk'], 5)
    assert precise and all('/one/ENTRY.cbl' in e['obj'] for e in precise)


def test_definition_answer_requires_both_import_and_definition_citations():
    from app.qa.answers import answer_issues
    sources = [dict(no=1, path='ENTRY.cbl', loc='L1-L2', text='       COPY RECORD-LAYOUT.\n'),
               dict(no=2, path='RECORD-LAYOUT.cpy', loc='L1-L2', text='       01 RECORD-DATA.\n')]
    answer = dict(summary='程序通过 COPY 引入定义。', why='字段位于 Copybook [2]。')
    assert answer_issues(answer, sources)
    assert not answer_issues(dict(answer, why='主程序引入 [1]，字段定义 [2]。'), sources)
