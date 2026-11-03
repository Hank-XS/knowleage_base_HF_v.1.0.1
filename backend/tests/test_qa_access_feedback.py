from types import SimpleNamespace
from sqlalchemy import select

from .test_hybrid_retrieval import retrieval_context, context, setup_project


def test_private_document_is_excluded_from_retrieval_and_original(retrieval_context):
    from app.db import KbDocument
    from app.qa.flow import SessionContext
    from app.knowledge.scope import question_scoped
    from app.knowledge.retrieval import retrieve
    from app.main import app
    from app.deps import current_user
    client,sessions,_,_=retrieval_context
    secret=client.post('/api/v1/knowledge/upload',files={'file':('private.md','# 内部阈值\n\n退款特殊审批值 SECRET-ONLY-721。'.encode())},
        data={'library_key':'private','project':'Private','version':'v1'}).json()['data']
    with sessions() as db:
        doc=db.get(KbDocument,secret['id']);doc.security='private';doc.author='owner';db.commit()
    class Runner:
        @question_scoped
        def run(self,ctx):return retrieve(ctx.question,'business_rule',[])
    assert Runner().run(SessionContext('view',user='viewer',role='dev',question='SECRET-ONLY-721 特殊审批值'))==[]
    app.dependency_overrides[current_user]=lambda:SimpleNamespace(username='viewer',role='dev')
    assert client.get(f'/api/v1/knowledge/docs/{secret["id"]}/original').status_code==403
    assert client.get(f'/api/v1/knowledge/docs/{secret["id"]}/chunks').status_code==403


def test_feedback_requires_ownership_and_does_not_verify_answer(retrieval_context):
    from app.main import app
    from app.deps import current_user
    from app.db import QaMessage
    from app.routers import qa
    client,sessions,_,_=retrieval_context
    # Router session factories are isolated just like the existing QA history fixtures.
    qa_session=qa.SessionLocal;qa.SessionLocal=sessions
    try:
        sid=client.post('/api/v1/qa/sessions').json()['data']['session_id']
        with sessions() as db:
            row=QaMessage(session_id=sid,question='test',answer_id='',hit_type='miss',payload_json={'review_status':'pending_review'})
            db.add(row);db.commit();aid=row.id
        result=client.post(f'/api/v1/qa/answers/{aid}/feedback',json={'kind':'wrong_source','comment':'依据不相关'})
        assert result.status_code==200
        with sessions() as db:
            payload=db.get(QaMessage,aid).payload_json
            assert payload['review_status']=='pending_review'
            assert payload['feedback'][0]['kind']=='wrong_source'
        app.dependency_overrides[current_user]=lambda:SimpleNamespace(username='other',role='dev')
        assert client.post(f'/api/v1/qa/answers/{aid}/feedback',json={'kind':'helpful'}).status_code==404
    finally:qa.SessionLocal=qa_session
