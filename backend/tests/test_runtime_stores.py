"""Only runtime indexes are loaded; old baseline data must never reappear."""
import json

from app.stores import graph, vector


def test_graph_ignores_legacy_then_persists_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(graph, 'DATA_DIR', tmp_path)
    legacy = tmp_path / 'graph_store.json'
    legacy.write_text(json.dumps({'nodes': [{'id': 'seed', 'label': 'CodeUnit', 'props': {}}], 'edges': []}))
    before = legacy.read_bytes()
    store = graph.MemGraphStore()
    assert store.node('seed') is None
    store.upsert_node('uploaded', 'CodeUnit', {'name': 'MAIN'})
    store.save()
    assert legacy.read_bytes() == before
    assert (tmp_path / 'runtime/graph_store.json').is_file()
    assert graph.MemGraphStore().node('uploaded')['props']['name'] == 'MAIN'


def test_vectors_ignore_legacy_then_persist_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(vector, 'DATA_DIR', tmp_path)
    legacy = tmp_path / 'vector_store.json'
    legacy.write_text(json.dumps({'kb_code_chunk': [{'id': 'seed', 'vector': [1], 'meta': {}}]}))
    before = legacy.read_bytes()
    store = vector.NumpyVectorStore()
    assert store.count('kb_code_chunk') == 0
    store.upsert('kb_code_chunk', 'uploaded', [1], {'text': 'MAIN'})
    store.save()
    assert legacy.read_bytes() == before
    assert (tmp_path / 'runtime/vector_store.json').is_file()
    assert vector.NumpyVectorStore().count('kb_code_chunk') == 1
