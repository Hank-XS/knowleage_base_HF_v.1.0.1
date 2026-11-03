import pytest

from app.knowledge.query_parser import parse_query, code_tokens, code_match
from .test_hybrid_retrieval import retrieval_context, context, setup_project, program, add


@pytest.mark.parametrize('text,mode', [
    ('余额不足时如何处理交易？', 'business'),
    ('这段代码在哪里？\n```cobol\nCALL "HELPER" USING WAIT-VALUE\n```', 'source'),
    ('```cobol\nMOVE A TO B\n```', 'source'),
    ('有没有相似实现？\n```cobol\nMOVE A TO B\n```', 'similar'),
    ('解释这段业务逻辑\n```cobol\nMOVE A TO B\n```', 'business'),
    ('解释“相似交易”的业务含义', 'business'),
    ('原代码在哪里？', 'source'),
    ('```cobol\nDISPLAY "similar"\n```', 'source'),
])
def test_server_routes_single_input(text, mode):
    assert parse_query(text).mode == mode


def test_literal_and_operator_changes_are_not_exact_or_same_cache():
    from app.knowledge.fingerprint import normalize_question
    first = 'MOVE "a b" TO VALUE-A'
    second = 'MOVE "A B" TO VALUE-A'
    assert code_match(first, second)[0] != 'exact_source'
    assert code_tokens('MOVE "a b" TO VALUE-A *> comment') == code_tokens(first)
    assert normalize_question(f'```cobol\n{first}\n```', 'x', []) != normalize_question(f'```cobol\n{second}\n```', 'x', [])


def test_source_identity_keeps_decimal_points_and_sentence_boundaries():
    assert code_tokens('MOVE 1.5 TO AMOUNT') != code_tokens('MOVE 1 5 TO AMOUNT')
    assert code_tokens('IF FLAG = 1 MOVE A TO B. DISPLAY C.') != code_tokens('IF FLAG = 1 MOVE A TO B DISPLAY C.')
    assert code_tokens('      MOVE A TO B.') == code_tokens('       MOVE A TO B.')


def test_pasted_call_does_not_scope_to_dependency_and_retains_original_lines(retrieval_context):
    from app.qa.flow import SessionContext
    from app.knowledge.scope import question_scoped, active_scope
    from app.knowledge.retrieval import retrieve
    client, _, _, _ = retrieval_context
    source = program('OWNER-RUN', 'DEPENDENCY')
    add(client, 'Source project', 'origin', {'OWNER.cbl': source})
    add(client, 'Dependency project', 'dep', {'DEPENDENCY.cbl': program('DEPENDENCY', 'OTHER')})
    class Runner:
        @question_scoped
        def run(self, ctx):
            assert active_scope().paths is None
            return retrieve(ctx.question, 'code_understanding', [])
    results = Runner().run(SessionContext('test', question='这段代码在哪里？\n```cobol\nCALL \'DEPENDENCY\' USING WAIT-VALUE\n```'))
    exact = [e for e in results if e.get('relation_type') == 'exact_source']
    assert exact and '/OWNER.cbl' in exact[0]['path']
    begin, end = map(int, exact[0]['loc'].replace('L', '').split('-'))
    assert exact[0]['text'] == ''.join(source.decode().splitlines(keepends=True)[begin - 1:end])
    assert active_scope() is None


def test_followup_reuses_code_but_new_question_does_not():
    previous = {'question':'```cobol\nMOVE A TO B\n```'}
    assert parse_query('有没有类似的实现呢？', [previous]).code
    assert parse_query('退款审批需要哪些资料？', [previous]).code == ''


def test_fenced_fixed_format_comments_keep_their_columns():
    code='      * similar is a source comment\n       MOVE "a b" TO VALUE-A\n'
    plan=parse_query('这段代码出自哪里？\n```cobol\n'+code+'```')
    assert plan.mode=='source' and plan.code.startswith('      *')
    assert code_tokens(plan.code)==code_tokens('MOVE "a b" TO VALUE-A')


def test_renamed_code_can_recall_other_programs(retrieval_context):
    from app.knowledge.retrieval import vector_evidence
    client, _, _, _ = retrieval_context
    add(client, 'Search project', 'similar', {'WORK.cbl': program('WORK-RUN', 'SERVICE')})
    hits = vector_evidence('有没有类似实现？\n```cobol\nMOVE INPUT-DATA TO AMOUNT-DATA\nCALL \'SERVICE\' USING AMOUNT-DATA\n```', ['kb_code_chunk'], 5)
    assert any(e.get('relation_type') == 'similar_logic' for e in hits)
