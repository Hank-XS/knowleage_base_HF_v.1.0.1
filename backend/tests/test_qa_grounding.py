"""Cross-project scope, exact previews, deduplication and citation integrity, without API calls."""
import json

from .test_hybrid_retrieval import retrieval_context, context, setup_project, program, add


def test_preview_content_really_matches_reported_lines(retrieval_context):
    from app.tools.handlers import tool_preview_source
    from app.db import KbDocument
    from sqlalchemy import select
    client, sessions, _, _ = retrieval_context
    content = program('LINE-CHECK', 'REMOTE-HELPER').decode() + ''.join(f'      * source line {n}\n' for n in range(12, 120))
    add(client, 'Line checks', 'lines', {'ENTRY.cbl': content.encode()})
    with sessions() as db:
        path = db.scalar(select(KbDocument.source_path))
    result = tool_preview_source(path=path, source_type='cobol', ref='ENTRY', loc='L21-L26')
    assert result['content'] == ''.join(content.splitlines(keepends=True)[20:26])
    assert result['loc'] == 'L21-L26' and result['type'] == 'code'
    assert not tool_preview_source(path=path, loc='L999-L1000')['available']
    bounded = tool_preview_source(path=path, source_type='code', loc='L1-L115')
    assert bounded['loc'] == 'L1-L80' and len(bounded['content'].splitlines()) == 80


def test_registry_merges_overlapping_code_and_preview_but_preserves_versions():
    from app.knowledge.evidence import EvidenceRegistry
    registry = EvidenceRegistry()
    source = [f'line {n}\n' for n in range(1, 21)]
    first = dict(channel='code', ref='TARGET-PARAGRAPH', path='src/ENTRY.cbl', version='v1', loc='L10-L15', text=''.join(source[9:15]))
    assert registry.add(first) == 1
    assert registry.add(dict(first, channel='cobol', ref='ENTRY.cbl', loc='L8-L20', text=''.join(source[7:20]))) == 1
    assert registry.sources()[0]['loc'] == 'L8-L20'
    assert registry.items[0]['text'] == ''.join(source[7:20])
    assert registry.sources()[0]['type'] == 'code'
    assert registry.add(dict(first, version='v2')) == 2
    assert registry.add(dict(first, loc='L1-L4', text=''.join(source[:4]))) == 3
    assert [s['no'] for s in registry.sources()] == [1, 2, 3]
    # Legacy indexes may omit library metadata while preview resolves it from the catalog.
    immutable = EvidenceRegistry()
    uploaded = dict(first, path='kb-raw/projects/job-unique/source/ENTRY.cbl', library='')
    assert immutable.add(uploaded) == 1
    assert immutable.add(dict(uploaded, channel='cobol', ref='ENTRY.cbl', library='library-A')) == 1


def test_api_keeps_original_subject_through_model_tools(retrieval_context, monkeypatch):
    from app.llm.base import ApiLLM
    from app.tools import agent
    from app.qa.flow import SessionContext
    from app.knowledge.scope import active_scope
    from app.db import KbDocument
    from sqlalchemy import select
    client, sessions, _, _ = retrieval_context
    add(client, 'Fee project', 'fees', {'ENTRY.cbl': program('BILL-RUN', 'EXTERNAL-BILL')})
    add(client, 'Other project', 'other', {'OTHER.cbl': program('UNRELATED', 'WRONG-SERVICE')})
    with sessions() as db:
        wrong = db.scalar(select(KbDocument.source_path).where(KbDocument.project == 'Other project'))
    llm = ApiLLM()
    monkeypatch.setattr(agent, 'get_llm', lambda: llm)
    monkeypatch.setattr(agent.AgentOrchestrator, '_persist', lambda *a, **kw: None)
    rounds = []
    def chat(messages, **kwargs):
        rounds.append(messages.copy())
        if len(rounds) == 1:
            return dict(content='', tool_calls=[
                dict(id='search', function=dict(name='search_code', arguments=json.dumps({'query': 'EXIT CONTINUE 的调用参数是什么'}))),
                dict(id='wrong', function=dict(name='preview_source', arguments=json.dumps({'path': wrong, 'source_type': 'code'})))])
        tools = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        assert all('OTHER.cbl' not in h['path'] for h in tools[0]['results'])
        assert tools[1]['available'] is False
        initial = json.loads(messages[1]['content'].split('稳定编号）：\n')[1])
        assert initial['results'][0]['channel'] == 'code'
        assert 'EXTERNAL-BILL' in initial['results'][0]['snippet']
        return dict(content=json.dumps(dict(summary='调用 EXTERNAL-BILL，参数为 WAIT-VALUE。', why='调用语句直接给出程序和参数 [1]。')), tool_calls=[])
    monkeypatch.setattr(llm, 'chat_tools', chat)
    result = agent.agent_flow.run(SessionContext('isolated', question='Fee project 中 BILL-RUN 调用什么程序，参数是什么？'))
    assert result.answer['summary'].startswith('调用 EXTERNAL-BILL')
    assert len(result.sources) == 1 and 'ENTRY.cbl' in result.sources[0]['path']
    assert active_scope() is None


def test_uncited_noise_is_removed_and_citations_are_remapped_together():
    from app.qa.answers import finish_answer
    sources = [dict(no=n, ref=f'ref{n}', loc='', snippet='source', path=f'{n}.cbl') for n in range(1, 10)]
    answer, kept = finish_answer(dict(summary='该段落是占位实现。', why='仅有注释和 EXIT [4]，对应静态关系 [2]。', caveats=[]), sources)
    assert [s['ref'] for s in kept] == ['ref2', 'ref4']
    assert '[2]' in answer['why'] and '[1]' in answer['why'] and '[4]' not in answer['why']
    missing, kept = finish_answer(dict(summary='未经支持的结论', why='见 [99]'), sources)
    assert missing['uncovered'] is True and missing['confidence'] == 0 and kept == []
    no_evidence, _ = finish_answer(dict(summary='模型凭记忆作答'), [])
    assert no_evidence['uncovered'] is True


def test_invalid_citation_is_repaired_once_using_actual_passages():
    from app.qa.answers import repair_answer
    class LLM:
        calls = 0
        def chat(self, messages, **kwargs):
            self.calls += 1
            assert 'exact body' in messages[1]['content']
            return json.dumps(dict(summary='没有实现计算。', why='段落只包含 EXIT [1]。'))
    llm = LLM()
    answer, sources = repair_answer(llm, dict(summary='不可靠', why='见 [99]'),
        [dict(no=1, ref='SECTION', loc='L10-L11', snippet='short', text='exact body')], '是否实现？')
    assert llm.calls == 1 and answer['summary'] == '没有实现计算。'
    assert sources[0]['no'] == 1 and 'text' not in sources[0]


def test_coverage_review_does_not_automatically_certify_a_partial_answer():
    from app.qa.answers import repair_answer
    class LLM:
        calls = 0
        def chat(self, messages, **kwargs):
            self.calls += 1
            assert '核心问题' in messages[1]['content'] and '实际费率是多少' in messages[1]['content']
            return json.dumps(dict(summary='无法给出实际费率，现有证据只定义了费率字段。',
                why='字段定义见 [1]。', caveats=[], confidence=.7, uncovered=True))
    llm = LLM()
    answer, sources = repair_answer(llm, dict(summary='无法给出实际费率。', why='字段见 [1]。',
        caveats=[], confidence=.7, uncovered=False),
        [dict(no=1, ref='RATE', loc='L1-L1', text='05 RATE PIC 9V99.')], '实际费率是多少？')
    assert llm.calls == 1 and answer['uncovered'] and sources


def test_cited_unknown_answer_can_keep_uncovered_after_one_review():
    from app.qa.answers import repair_answer
    answer = dict(summary='无法给出实际费率。', why='只有字段定义 [1]。', caveats=[], confidence=.8, uncovered=True)
    class LLM:
        calls = 0
        def chat(self, *args, **kwargs):
            self.calls += 1
            return json.dumps(answer)
    llm = LLM()
    checked, sources = repair_answer(llm, answer, [dict(no=1, ref='RATE', loc='L1-L1', text='05 RATE PIC 9V99.')], '实际费率是多少？')
    assert checked['uncovered'] and sources and llm.calls == 1


def test_retrieval_miss_cannot_claim_the_entire_knowledge_base_has_no_data():
    from app.qa.answers import finish_answer
    answer, sources = finish_answer(dict(summary='知识库中没有这项规则。', why='只有相关字段 [1]。',
        caveats=[], uncovered=True), [dict(no=1, ref='FIELD', loc='L1-L1', snippet='field', path='field.cpy')])
    assert answer['uncovered'] and sources == []
    assert '知识库中没有' not in answer['summary']


def test_prompt_has_general_grounding_rules_without_fixture_names():
    from app.qa.answers import ANSWER_GUIDANCE
    from app.qa.prompts import build_synthesis_messages
    from app.tools.agent import SYSTEM_PROMPT
    prompt = build_synthesis_messages('general', 'question', ['evidence'])[0]['content']
    for text in (prompt, SYSTEM_PROMPT):
        assert '不证明运行时必然执行' in text
        assert '不推出金额为零' in text
        assert '不说明业务单位' in text
        assert 'how 仅在用户询问' in text
        assert not any(name in text for name in ('COBSWAIT', 'CBACT04C', 'MVSWAIT'))


def test_followup_field_keeps_project_but_new_subject_switches(retrieval_context):
    from app.knowledge.scope import question_scoped, active_scope
    from app.knowledge.retrieval import vector_evidence
    from app.qa.flow import SessionContext
    client, _, _, _ = retrieval_context
    add(client, 'First project', 'first', {'FIRST.cbl': program('FIRST-RUN', 'FIRST-SVC')})
    add(client, 'Second project', 'second', {'SECOND.cbl': program('SECOND-RUN', 'SECOND-SVC')})
    class Query:
        @question_scoped
        def run(self, ctx):
            return vector_evidence(ctx.question, ['kb_code_chunk'], 5)
    history = [dict(question='First project 中 FIRST-RUN 调用什么？')]
    followup = Query().run(SessionContext('followup', question='WAIT-VALUE 的定义是什么？', history=history))
    assert followup and all('FIRST.cbl' in e['path'] for e in followup)
    changed = Query().run(SessionContext('changed', question='SECOND-RUN 调用什么？', history=history))
    assert changed and all('SECOND.cbl' in e['path'] for e in changed)
    assert active_scope() is None


def test_same_named_objects_never_produce_mixed_facts(retrieval_context):
    from app.knowledge.retrieval import retrieve
    from app.knowledge.evidence import EvidenceRegistry
    from app.qa.answers import finish_answer
    client, _, _, _ = retrieval_context
    add(client, 'East project', 'east', {'BATCH.cbl': program('BATCH', 'EAST-SVC')})
    add(client, 'West project', 'west', {'BATCH.cbl': program('BATCH', 'WEST-SVC')})
    hits = retrieve('BATCH.cbl 调用了哪个程序？', 'code_understanding', ['BATCH'])
    assert all(e['kind'] == 'ambiguous_scope' for e in hits)
    answer, sources = finish_answer(dict(summary='模型试图猜测一个程序'), EvidenceRegistry(hits).sources())
    assert answer['uncovered'] and 'East project' in answer['summary'] and 'West project' in answer['summary']
    assert sources == []
