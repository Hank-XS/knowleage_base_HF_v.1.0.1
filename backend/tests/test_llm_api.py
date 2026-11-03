"""Provider contracts, without making paid requests."""
import httpx
import pytest

from app.config import Settings, settings
from app.llm.base import ApiLLM


def test_deepseek_key_is_only_used_for_official_host(monkeypatch):
    monkeypatch.delenv('KB_LLM_API_KEY', raising=False)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    common = dict(_env_file=None, deepseek_api_key='secret', kb_llm_api_key='')
    assert Settings(**common, kb_llm_base_url='https://api.deepseek.com/v1').kb_llm_api_key == 'secret'
    assert Settings(**common, kb_llm_base_url='https://another.example').kb_llm_api_key == ''


def mock_response(monkeypatch, message, finish='stop'):
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': message, 'finish_reason': finish}]})
    monkeypatch.setattr('app.llm.base.httpx.post', post)
    return requests


def test_tool_reasoning_survives_agent_roundtrip(monkeypatch):
    from app.qa.flow import SessionContext
    from app.tools.agent import AgentOrchestrator
    monkeypatch.setattr(settings, 'kb_llm_base_url', 'https://api.deepseek.com')
    monkeypatch.setattr(settings, 'kb_llm_thinking', 'enabled')
    calls = []
    tool_call = {'id': 'call1', 'type': 'function', 'function': {'name': 'search_code', 'arguments': '{"query":"DEMO"}'}}
    def post(url, **kwargs):
        body = kwargs['json']
        calls.append(body)
        assert body['thinking'] == {'type': 'enabled'}
        if len(calls) == 1:
            message = dict(role='assistant', content=None, reasoning_content='provider state', tool_calls=[tool_call])
        else:
            assert body['messages'][2]['reasoning_content'] == 'provider state'
            message = dict(role='assistant', content='{"summary":"DEMO","uncovered":false}')
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices': [{'message': message, 'finish_reason': 'stop'}]})
    monkeypatch.setattr('app.llm.base.httpx.post', post)
    monkeypatch.setattr('app.tools.agent.invoke_tool', lambda *a: {'results': [{'ref': 'DEMO', 'snippet': 'DEMO'}]})
    monkeypatch.setattr(AgentOrchestrator, '_persist', lambda *a, **kw: None)
    result = AgentOrchestrator()._run_api(SessionContext('test', question='DEMO'), ApiLLM(), 0)
    assert result.answer['summary'] == 'DEMO'
    assert len(calls) == 2


@pytest.mark.parametrize('message,finish', [({'content': '   '}, 'stop'), ({'content': '{"summary":'}, 'length')])
def test_blank_and_truncated_answers_are_not_success(monkeypatch, message, finish):
    mock_response(monkeypatch, message, finish)
    with pytest.raises(ValueError):
        ApiLLM().chat([{'role': 'user', 'content': 'JSON'}], json_mode=True)


def test_generic_provider_does_not_receive_deepseek_options(monkeypatch):
    monkeypatch.setattr(settings, 'kb_llm_base_url', 'https://other.example/v1')
    requests = mock_response(monkeypatch, {'content': '{"summary":"ok"}'})
    assert ApiLLM().chat([], json_mode=True) == '{"summary":"ok"}'
    assert 'thinking' not in requests[0]
    assert requests[0]['response_format'] == {'type': 'json_object'}


def test_agent_preview_and_duplicate_citations_keep_stable_numbers():
    from app.tools.agent import _collect_evidence, _sources_from_evidences
    evidence = []
    first = {'results': [dict(ref='RUN', path='RUN.cbl', loc='L1-L4', snippet='header')]}
    _collect_evidence(first, 'search_code', evidence)
    duplicate = {'results': [dict(ref='RUN', path='RUN.cbl', loc='L1-L4', snippet='header')]}
    _collect_evidence(duplicate, 'search_code', evidence)
    preview = dict(available=True, type='code', title='RUN', path='RUN.cbl', loc='', content='full source')
    _collect_evidence(preview, 'preview_source', evidence)
    assert first['results'][0]['source_no'] == duplicate['results'][0]['source_no'] == 1
    assert preview['source_no'] == 2
    sources = _sources_from_evidences(evidence)
    assert [s['no'] for s in sources] == [1, 2]
    assert sources[1]['snippet'] == 'full source'


def test_embedding_provider_indices_are_reordered_and_validated(monkeypatch):
    from app.llm.base import ApiEmbedder
    def post(url,**kwargs):
        return httpx.Response(200,request=httpx.Request('POST',url),json={'data':[{'index':1,'embedding':[0.,1.]},{'index':0,'embedding':[1.,0.]}]})
    monkeypatch.setattr('app.llm.base.httpx.post',post)
    assert ApiEmbedder().embed(['first','second'])==[[1.,0.],[0.,1.]]
    def broken(url,**kwargs):
        return httpx.Response(200,request=httpx.Request('POST',url),json={'data':[{'index':None,'embedding':[1.]}]})
    monkeypatch.setattr('app.llm.base.httpx.post',broken)
    with pytest.raises(ValueError):ApiEmbedder().embed(['first'])
