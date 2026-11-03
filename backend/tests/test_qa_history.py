import datetime as dt
import json

from .test_code_projects import setup_project


def test_history_restore_search_and_session_ownership(setup_project, monkeypatch):
    from app import db as database
    from app import deps
    from app.qa import flow as flow_module
    from app.routers import qa
    from app.llm.base import MockLLM
    from app.knowledge import catalog

    client, sessions, _, _ = setup_project
    monkeypatch.setattr(database, 'SessionLocal', sessions)
    monkeypatch.setattr(deps, 'SessionLocal', sessions)
    monkeypatch.setattr(qa, 'SessionLocal', sessions)
    monkeypatch.setattr(catalog, 'SessionLocal', sessions)
    monkeypatch.setattr(flow_module, 'SessionLocal', sessions)
    monkeypatch.setattr(flow_module, 'get_llm', lambda: MockLLM())
    monkeypatch.setattr(flow_module.retrieval, 'retrieve', lambda *args: [])
    monkeypatch.setattr(flow_module.registry, 'invoke', lambda *args: dict(route='miss'))
    session_id = client.post('/api/v1/qa/sessions').json()['data']['session_id']
    assert client.get('/api/v1/qa/sessions').json()['data']['total'] == 0
    answers = []
    for question in ['解释入口程序', '后续问题完成度100%']:
        response = client.post('/api/v1/qa/ask', json=dict(session_id=session_id, question=question))
        assert response.status_code == 200, response.text
        answers.append(response.json()['data'])
    history = client.get(f'/api/v1/qa/sessions/{session_id}/history').json()['data']
    assert len(history) == 2
    assert history[0]['answer_id'] == answers[0]['answer_id']
    assert history[0]['answer']['summary'] == answers[0]['answer']['summary']
    assert history[0]['reasoning_trace'] and history[0]['created_at'].endswith('+00:00')
    rejected = client.post(f"/api/v1/qa/answers/{answers[0]['answer_id']}/review", json={'verdict': 'rejected'})
    assert rejected.status_code == 200
    restored = client.get(f'/api/v1/qa/sessions/{session_id}/history').json()['data']
    assert restored[0]['review_status'] == 'rejected'
    listing = client.get('/api/v1/qa/sessions', params={'keyword': '100%'}).json()['data']
    assert listing['total'] == 1 and listing['items'][0]['title'] == '解释入口程序'
    assert listing['items'][0]['message_count'] == 2
    assert client.get('/api/v1/qa/sessions', params={'keyword': '无此问题'}).json()['data']['total'] == 0
    with sessions() as db:
        other = database.QaSession(user='another-user'); db.add(other); db.flush(); other_id = other.id
        db.add(database.QaMessage(session_id=other_id, question='其他用户的记录', answer_id='', payload_json={}))
        db.commit()
    assert client.get('/api/v1/qa/sessions').json()['data']['total'] == 1
    assert client.get(f'/api/v1/qa/sessions/{other_id}/history').status_code == 404
    for route in ['ask', 'ask_agent', 'followup']:
        response = client.post(f'/api/v1/qa/{route}', json=dict(session_id=other_id, question='继续', answer_id='unused'))
        assert response.status_code == 404


def test_session_pagination_excludes_empty_sessions(setup_project, monkeypatch):
    from app.db import QaSession, QaMessage
    from app.routers import qa
    client, sessions, _, _ = setup_project
    monkeypatch.setattr(qa, 'SessionLocal', sessions)
    with sessions() as db:
        db.add(QaSession(user='tester'))
        for index in range(22):
            session = QaSession(user='tester'); db.add(session); db.flush()
            db.add(QaMessage(session_id=session.id, question=f'问题{index}', answer_id='',
                             created_at=dt.datetime(2026, 11, 2, 0, index), payload_json={}))
        db.commit()
    first = client.get('/api/v1/qa/sessions').json()['data']
    second = client.get('/api/v1/qa/sessions', params={'page': 2}).json()['data']
    assert first['total'] == 22 and len(first['items']) == 20 and len(second['items']) == 2
    assert first['items'][0]['title'] == '问题21'
    assert not {s['session_id'] for s in first['items']} & {s['session_id'] for s in second['items']}


def test_answer_contract_preserves_detail_and_supports_legacy_answers():
    from app.qa.answers import parse_answer
    from app.qa.prompts import build_synthesis_messages
    from app.tools.agent import _parse_answer, SYSTEM_PROMPT
    long_detail = '完整说明。' * 300
    answer = dict(summary='先给简明结论，然后列出必要操作。', what='结论', why=long_detail, how='关键操作', caveats=['条件限制'])
    for parser in (parse_answer, _parse_answer):
        parsed = parser(json.dumps(answer, ensure_ascii=False))
        assert parsed['summary'] == answer['summary'] and parsed['why'] == long_detail
        assert parser('{"what":"旧答案","how":"旧操作"}')['summary'] == '旧答案'
    prompt = build_synthesis_messages('general', '测试问题', [])[0]['content']
    assert 'summary' in prompt and '120' in prompt
    assert 'summary' in SYSTEM_PROMPT and '不描述检索步骤' in SYSTEM_PROMPT
