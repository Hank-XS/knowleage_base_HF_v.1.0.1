import pytest
from sqlalchemy import select

from .test_documents_catalog import context
from .test_code_projects import setup_project
from .test_cross_projects import add


def program(name, service):
    return f'''       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WAIT-VALUE PIC 9(8) COMP.
       01 INPUT-VALUE PIC X(8).
       PROCEDURE DIVISION.
           ACCEPT INPUT-VALUE FROM SYSIN.
           MOVE INPUT-VALUE TO WAIT-VALUE.
           CALL '{service}' USING WAIT-VALUE.
           GOBACK.
'''.encode()


@pytest.fixture
def retrieval_context(context, monkeypatch):
    from app.knowledge import retrieval
    from app.qa import analyzer
    client, sessions, graph, vectors = context
    monkeypatch.setattr(retrieval, 'graph_store', graph)
    monkeypatch.setattr(retrieval, 'vector_store', vectors)
    monkeypatch.setattr(analyzer, 'graph_store', graph)
    return client, sessions, graph, vectors


def test_new_project_program_id_and_original_gap_are_retrievable_without_reslicing(retrieval_context):
    from app.knowledge.retrieval import vector_evidence
    from app.db import KbDocVersion, KbDocChunk
    client, sessions, graph, vectors = retrieval_context
    job = add(client, '付款作业', 'payments', {'src/ENTRY001.cbl': program('PAY-ENTRY', 'SVC-REMOTE')})
    with sessions() as db:
        texts = db.scalars(select(KbDocChunk.text)).all()
        assert not any("CALL 'SVC-REMOTE'" in text for text in texts), 'Fixture exercises a real coverage gap'
        original = db.scalar(select(KbDocVersion.content))
    before = vectors.count('kb_code_chunk')
    hits = vector_evidence('PAY-ENTRY 程序调用哪个外部程序？传递什么参数？', ['kb_code_chunk'], 5)
    assert hits[0]['kind'] == 'source_context'
    assert "CALL 'SVC-REMOTE' USING WAIT-VALUE" in hits[0]['text']
    begin, end = [int(x) for x in hits[0]['loc'].replace('L', '').split('-')]
    assert hits[0]['text'] == ''.join(original.splitlines(keepends=True)[begin - 1:end])
    assert vectors.count('kb_code_chunk') == before
    # No startup reindex or code change is needed for a wholly different new upload.
    add(client, '发票作业', 'invoices', {'jobs/BATCH009.cbl': program('INVOICE-WRITER', 'SVC-ARCHIVE')})
    fresh = vector_evidence('INVOICE-WRITER 程序调用哪个外部程序？', ['kb_code_chunk'], 5)
    assert "CALL 'SVC-ARCHIVE'" in fresh[0]['text']
    assert all('/BATCH009.cbl' in e['obj'] for e in fresh)


def test_current_versions_and_cleanup_invalidate_recall(retrieval_context):
    from app.knowledge.retrieval import vector_evidence
    from app.knowledge import maintenance
    client, sessions, _, vectors = retrieval_context
    first = add(client, '工资作业', 'salary', {'RUN.cbl': program('SALARY-RUN', 'OLD-SVC')})
    query = 'SALARY-RUN 程序调用哪个外部程序？'
    assert 'OLD-SVC' in vector_evidence(query, ['kb_code_chunk'], 5)[0]['text']
    second = add(client, '工资作业', 'salary', {'RUN.cbl': program('SALARY-RUN', 'NEW-SVC')}, version='v2')
    hits = vector_evidence(query, ['kb_code_chunk'], 5)
    assert 'NEW-SVC' in hits[0]['text'] and all(first not in h['obj'] for h in hits)
    body = dict(target='chunks', job_id=second)
    preview = maintenance.preview(body); maintenance.execute(body, preview['token'])
    assert vector_evidence(query, ['kb_code_chunk'], 5) == []


def test_same_named_files_require_scope_and_unknown_file_does_not_use_hash_noise(retrieval_context):
    from app.knowledge.retrieval import vector_evidence
    client, _, _, _ = retrieval_context
    add(client, '国内工程', 'one', {'SHARED.cbl': program('SHARED', 'LOCAL-SVC')})
    add(client, '海外工程', 'two', {'SHARED.cbl': program('SHARED', 'REMOTE-SVC')})
    ambiguous = vector_evidence('SHARED.cbl 程序调用哪个外部程序？', ['kb_code_chunk'], 5)
    assert len(ambiguous) == 2 and all(e['kind'] == 'ambiguous_scope' for e in ambiguous)
    scoped = vector_evidence('国内工程的 SHARED.cbl 程序调用哪个外部程序？', ['kb_code_chunk'], 5)
    assert 'LOCAL-SVC' in scoped[0]['text'] and all('REMOTE-SVC' not in e['text'] for e in scoped)
    assert vector_evidence('NOT-UPLOADED.cbl 程序调用什么？', ['kb_code_chunk'], 5) == []
    add(client, '国内工程', 'one', {'ENTRY-A.cbl': program('CENTRAL-ENTRY', 'LOCAL-ENTRY')}, version='v2')
    add(client, '海外工程', 'two', {'ENTRY-B.cbl': program('CENTRAL-ENTRY', 'REMOTE-ENTRY')}, version='v2')
    renamed = vector_evidence('CENTRAL-ENTRY 程序调用哪个外部程序？', ['kb_code_chunk'], 5)
    assert len(renamed) == 2 and all(e['kind'] == 'ambiguous_scope' for e in renamed)
    # Naming the physical file is more specific than the shared PROGRAM-ID.
    exact_file = vector_evidence('ENTRY-A.cbl 中 CENTRAL-ENTRY 程序调用什么？', ['kb_code_chunk'], 5)
    assert 'LOCAL-ENTRY' in exact_file[0]['text'] and all('REMOTE-ENTRY' not in e['text'] for e in exact_file)


def test_document_lexical_recall_is_not_specific_to_a_code_project(retrieval_context):
    from app.knowledge.retrieval import vector_evidence
    client, _, _, _ = retrieval_context
    response = client.post('/api/v1/knowledge/upload', files={'file': ('refund.md', '# 退款流程\n\n退款申请必须先核对原交易编号，再记录退款原因。'.encode())},
        data={'library_key': 'service', 'project': '退款服务', 'version': 'v1'})
    assert response.status_code == 200
    hits = vector_evidence('退款申请如何处理？', ['kb_doc_chunk'], 5)
    assert hits and '原交易编号' in hits[0]['text']
    assert vector_evidence('量子纠缠实验步骤', ['kb_doc_chunk'], 5) == []


def test_agent_and_flow_put_instruction_before_graph_summary(retrieval_context, monkeypatch):
    from app.routers import qa
    from app.qa import flow
    from app.tools import agent
    from app.knowledge import cache
    from app.llm.base import MockLLM
    client, sessions, _, _ = retrieval_context
    for module in (qa, flow, agent, cache):
        monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(agent, 'get_llm', lambda: MockLLM())
    monkeypatch.setattr(flow, 'get_llm', lambda: MockLLM())
    add(client, '审计作业', 'audit', {'OTHER-NAME.cbl': program('Z9-BATCH', 'DYNAMIC-SVC9')})
    for route in ('ask', 'ask_agent'):
        session = client.post('/api/v1/qa/sessions').json()['data']['session_id']
        response = client.post(f'/api/v1/qa/{route}', json={'session_id': session, 'question': 'Z9-BATCH 程序调用什么外部程序？参数是什么？'})
        assert response.status_code == 200, response.text
        answer = response.json()['data']
        assert "CALL 'DYNAMIC-SVC9' USING WAIT-VALUE" in answer['answer']['summary']
        assert answer['sources'][0]['type'] == 'code'


def test_identifier_boundaries_do_not_match_a_prefix(retrieval_context):
    from app.qa.analyzer import extract_entities
    client, _, _, _ = retrieval_context
    add(client, '边界测试', 'boundaries', {'NAME.cbl': program('ALPHA1', 'EXTERNAL1')})
    assert 'ALPHA1' not in extract_entities('ALPHA12 程序如何工作？')
    assert 'ALPHA1' in extract_entities('ALPHA1程序如何工作？')


def test_verified_cache_does_not_bypass_new_version_or_new_name_collision(retrieval_context, monkeypatch):
    from app.db import VerifiedAnswer
    from app.knowledge import cache
    client, sessions, _, _ = retrieval_context
    monkeypatch.setattr(cache, 'SessionLocal', sessions)
    first = add(client, '计算作业', 'calc', {'RUN.cbl': program('RUN', 'OLD-CALL')})
    with sessions() as db:
        db.add(VerifiedAnswer(fingerprint='known', question_norm='RUN', scene_code='general', answer_json={'what':'old'},
            status='verified', hit_type='miss', verified_by='tester', kb_version='v1', sources_json=[{'obj': f'kb-raw/projects/{first}/source/RUN.cbl'}]))
        db.commit()
    assert cache.lookup('known', 'RUN 程序调用什么？', 'general')['route'] == 'exact'
    add(client, '其他作业', 'other', {'RUN.cbl': program('RUN', 'OTHER-CALL')})
    assert cache.lookup('known', 'RUN 程序调用什么？', 'general')['route'] == 'miss'
    add(client, '计算作业', 'calc', {'RUN.cbl': program('RUN', 'NEW-CALL')}, version='v2')
    assert cache.lookup('known', '计算作业的 RUN 程序调用什么？', 'general')['route'] == 'miss'
