import pytest
from sqlalchemy import select
from .test_hybrid_retrieval import retrieval_context, context, setup_project


def test_generation_activation_rollback_and_changed_corpus_gate(retrieval_context,monkeypatch,tmp_path):
    from app.knowledge import indexing
    from app.llm.base import HashEmbedder
    from app.db import KbDocument,KbDocChunk
    client,sessions,_,store=retrieval_context
    monkeypatch.setattr(indexing,'DATA_DIR',tmp_path)
    doc=client.post('/api/v1/knowledge/upload',files={'file':('guide.md','# 退款\n\n核对原交易编号后处理退款。'.encode())},
        data={'library_key':'service','version':'v1'}).json()['data']
    original=store._path.read_bytes()
    report=indexing.rebuild(store,HashEmbedder(),stage_only=True)
    assert store._path.read_bytes()==original
    indexing.activate(store,report['generation_id'])
    assert store.manifest['generation_id']==report['generation_id']
    indexing.rollback(store,report['generation_id'])
    assert store.export('kb_doc_chunk')
    stage=indexing.rebuild(store,HashEmbedder(),stage_only=True)
    with sessions() as db:
        chunk=db.scalar(select(KbDocChunk).where(KbDocChunk.doc_id==doc['id']))
        db.delete(chunk);db.commit()
    with pytest.raises(ValueError,match='资料或权限已变化'):
        indexing.activate(store,stage['generation_id'])


def test_vector_model_failure_keeps_active_index(retrieval_context,monkeypatch,tmp_path):
    from app.knowledge import indexing
    client,_,_,store=retrieval_context
    monkeypatch.setattr(indexing,'DATA_DIR',tmp_path)
    client.post('/api/v1/knowledge/upload',files={'file':('sample.md','# 标题\n\n原始正文。'.encode())},data={'library_key':'service','version':'v1'})
    before=store._path.read_bytes()
    class Broken:
        name='broken'
        def embed(self,texts):raise RuntimeError('simulated provider failure')
    with pytest.raises(RuntimeError):indexing.rebuild(store,Broken())
    assert store._path.read_bytes()==before
