"""Document ingestion, versioned originals, and publication to the shared stores."""
import hashlib
from pathlib import Path
import uuid
from threading import RLock

from sqlalchemy import select

from ..db import SessionLocal, KbDocument, KbDocVersion, KbDocChunk, KbLibrary
from ..ingest.documents import extract_document
from ..llm import get_embedder
from ..stores.objects import object_store
from ..stores.graph import graph_store
from ..stores.vector import vector_store
from .catalog import classification, project_key


_upload_lock = RLock()


def upload_document(*, filename, content, library_key, version, project='', purpose='reference',
                    security='internal', author='admin', tags=None, official=True, auto_chunk=True):
    from .manage import _ensure_library, _doc_payload
    metadata = classification(library_key, project, purpose, tags)
    version = version.strip()
    if not version or len(version) > 32:
        raise ValueError('版本必填，且不能超过 32 个字符')
    filename = Path(filename.replace('\\', '/')).name
    parsed = extract_document(filename, content)
    lib = metadata['library']
    relative_path = f'uploads/{project_key(lib, metadata["project"])}/{filename}'
    with _upload_lock, SessionLocal() as db:
        if db.get(KbLibrary, lib) is None:
            _ensure_library(db, lib, lib)
        doc = db.scalar(select(KbDocument).where(KbDocument.library_key == lib,
                        KbDocument.project == metadata['project'], KbDocument.asset_type == 'document',
                        KbDocument.path == relative_path))
        if doc is None:
            doc = KbDocument(library_key=lib, name=Path(filename).stem, path=relative_path)
            db.add(doc)
            db.flush()
        key = f'kb-managed/documents/{doc.id}/{uuid.uuid4().hex}/{filename}'
        object_store.put(key, content)
        doc.version, doc.doc_type = version, Path(filename).suffix[1:].lower()
        doc.project, doc.purpose, doc.tags_json = metadata['project'], purpose, metadata['tags']
        doc.asset_type, doc.is_current = 'document', 1
        doc.size_bytes, doc.object_key, doc.source_path = len(content), key, key
        doc.author, doc.security, doc.official = author, security, int(official)
        doc.status, doc.vectorized = 'published', 1
        import datetime as dt
        doc.uploaded_at = dt.datetime.now(dt.timezone.utc)
        ver = db.scalar(select(KbDocVersion).where(KbDocVersion.doc_id == doc.id, KbDocVersion.version == version))
        if ver is None:
            ver = KbDocVersion(doc_id=doc.id, version=version)
            db.add(ver)
        ver.content, ver.object_key, ver.created_by = parsed['content'], key, author
        ver.meta_json = {'warnings': parsed['warnings'], 'parser': parsed['parser'], **metadata}
        db.query(KbDocChunk).filter(KbDocChunk.doc_id == doc.id, KbDocChunk.version == version).delete()
        chunks = [KbDocChunk(doc_id=doc.id, version=version, **{**chunk, 'title': chunk['title'][:256]}) for chunk in parsed['chunks']]
        db.add_all(chunks)
        db.flush()
        common = dict(doc_id=doc.id, library=lib, project=doc.project, purpose=purpose,
                      tags=doc.tags_json, version=version, is_current=True, source_path=key)
        embedder = get_embedder()
        embeddings = embedder.embed([chunk.text for chunk in chunks])
        old_nodes = [n for n in graph_store.dump()['nodes'] if n['props'].get('doc_id') == doc.id]
        old_ids = {n['id'] for n in old_nodes}
        old_edges = [e for e in graph_store.dump()['edges'] if e['src'] in old_ids or e['dst'] in old_ids]
        old_vectors = [c for c in vector_store._data['kb_doc_chunk'] if c['meta'].get('doc_id') == doc.id]
        try:
            vector_store.delete_by_meta('kb_doc_chunk', 'doc_id', doc.id)
            graph_store.delete_by_meta('doc_id', doc.id)
            system = 'library/' + hashlib.sha256(lib.encode()).hexdigest()[:24]
            graph_store.upsert_node(system, 'System', {'name': db.get(KbLibrary, lib).title, 'library': lib})
            node_id = 'document/' + doc.id
            graph_store.upsert_node(node_id, 'Document', {**common, 'name': doc.name, 'kind': 'document'})
            graph_store.upsert_edge(system, 'CONTAINS', node_id, common)
            for chunk, embedding in zip(chunks, embeddings):
                node = 'chunk/' + chunk.id
                graph_store.upsert_node(node, 'DocumentSection', {**common, 'name': chunk.title, **chunk.meta_json})
                graph_store.upsert_edge(node_id, 'CONTAINS', node, common)
                vector_store.upsert('kb_doc_chunk', chunk.id, embedding,
                                    {**common, 'title': chunk.title, 'text': chunk.text, 'doc_type': 'doc', 'embedding': embedder.name,
                                     'loc': chunk.title, **chunk.meta_json})
            graph_store.save()
            vector_store.save()
            db.commit()
        except Exception:
            db.rollback()
            graph_store.delete_by_meta('doc_id', common['doc_id'])
            vector_store.delete_by_meta('kb_doc_chunk', 'doc_id', common['doc_id'])
            for node in old_nodes:
                graph_store.upsert_node(node['id'], node['label'], node['props'])
            for edge in old_edges:
                graph_store.upsert_edge(edge['src'], edge['rel'], edge['dst'], edge['props'])
            for vector in old_vectors:
                vector_store.upsert('kb_doc_chunk', vector['id'], vector['vector'], vector['meta'])
            graph_store.save()
            vector_store.save()
            raise
        return {**_doc_payload(doc, content=parsed['content']), 'warnings': parsed['warnings'], 'chunk_count': len(chunks)}
