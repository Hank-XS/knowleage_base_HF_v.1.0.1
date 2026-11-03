import pytest

from app.knowledge.representations import children, encode_parent
from app.llm.base import HashEmbedder
from app.stores.vector import NumpyVectorStore


def test_children_reconstruct_original_spans_and_parent_is_preserved(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'kb_child_tokens', 64)
    text = ''.join(f'       MOVE FIELD-{i} TO TARGET-{i}.\n' for i in range(30))
    vector, meta = encode_parent('parent', text, dict(text=text, source_path='src/RUN.cbl', loc='L21-L50'), HashEmbedder())
    assert meta['text'] == text and len(meta['children']) > 1
    for child in meta['children']:
        assert child['text'] == text[child['start_offset']:child['end_offset']]
        begin, end = map(int, child['loc'].replace('L','').split('-'))
        assert child['text'] == ''.join(text.splitlines(keepends=True)[begin-21:end-20])
        assert len(child['vectors']) == 2


def test_embedding_failure_does_not_replace_live_generation(tmp_path):
    store = NumpyVectorStore();store._data = {'kb_doc_chunk':[], 'kb_code_chunk':[], 'kb_mapping_chunk':[]};store._path=tmp_path/'vectors.json'
    store.upsert('kb_code_chunk','old',[1.,0.],dict(text='old'))
    store.save();before=store._path.read_bytes()
    with pytest.raises(ValueError):
        store.replace_all({'kb_doc_chunk':[], 'kb_code_chunk':[dict(id='broken', vector=[float('nan')], meta={})], 'kb_mapping_chunk':[]})
    assert store._path.read_bytes() == before
    assert store.export('kb_code_chunk')[0]['id']=='old'


def test_stale_generation_cannot_overwrite_new_upload(tmp_path):
    store = NumpyVectorStore();store._path=tmp_path/'vectors.json'
    old=store.revision;store.upsert('kb_doc_chunk','new',[1.],{'text':'new'})
    with pytest.raises(ValueError):
        store.replace_all({c:[] for c in store._data}, expected_revision=old)


def test_vector_acl_filters_before_top_k(tmp_path):
    store=NumpyVectorStore();store._data={c:[] for c in store._data};store._path=tmp_path/'vectors.json'
    store.upsert('kb_doc_chunk','secret',[1.,0.],{'source_path':'private'})
    store.upsert('kb_doc_chunk','public',[.8,.2],{'source_path':'public'})
    assert store.search('kb_doc_chunk',[1.,0.],1,exclude_paths={'private'})[0]['id']=='public'


def test_budget_keeps_real_line_ranges():
    from app.knowledge.passage import pack
    text=''.join(f'line {n}\n' for n in range(100))
    result=pack([dict(text=text,loc='L21-L120',path='x')],budget=256)
    assert len(result)==1
    begin,end=map(int,result[0]['loc'].replace('L','').split('-'))
    assert result[0]['text']==''.join(text.splitlines(keepends=True)[:end-begin+1])
    assert len(result[0]['text'].encode())+128<=256


def test_parents_share_one_embedding_batch():
    from app.knowledge.representations import encode_many
    class Encoder(HashEmbedder):
        calls=0
        def embed(self,texts):
            self.calls+=1
            return super().embed(texts)
    encoder=Encoder()
    result=encode_many([('a','first',{'text':'first'}),('b','second',{'text':'second'})],encoder)
    assert encoder.calls==1 and len(result)==2


def test_original_file_purpose_is_indexed_with_its_actual_lines():
    from app.knowledge.representations import encode_many,file_overview
    body='      * FUNCTION : Calculate interest.\n'+'      * license\n'*30+'       MOVE A TO B.\n'
    _,meta=encode_many([('field','       MOVE A TO B.\n',dict(text='       MOVE A TO B.\n',source_path='RUN.cbl',loc='L32-L32',file_overview=file_overview(body,'RUN.cbl')))],HashEmbedder())[0]
    row=dict(id='field',vector=[1.],meta=meta)
    overview=next(p for p in NumpyVectorStore.passages(row) if p['meta']['parent_id'].startswith('overview-'))
    assert overview['meta']['title']=='RUN.cbl'
    begin,end=map(int,overview['meta']['loc'].replace('L','').split('-'))
    assert overview['meta']['text']==''.join(body.splitlines(keepends=True)[begin-1:end])
