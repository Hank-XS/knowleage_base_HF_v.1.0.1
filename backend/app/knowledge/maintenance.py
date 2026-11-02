"""Explicitly scoped cleanup with an affected-count preview and stale-preview checks."""
from copy import deepcopy
import hashlib
import json
from threading import RLock

from sqlalchemy import select

from .. import db as database
from ..stores import graph as graphs, vector as vectors
from .browsing import file_label
from .document_service import _upload_lock
from .graph_view import file_node_ids

_lock = RLock()


def _selection(db, body):
    doc_id, job_id = body.get('doc_id', ''), body.get('job_id', '')
    if doc_id and job_id:
        raise ValueError('请只选择一个文件或工程版本')
    if doc_id:
        doc = db.get(database.KbDocument, doc_id)
        if not doc:
            raise ValueError('文件不存在')
        docs = [doc]
        version = body.get('version') or doc.version
        if not db.scalar(select(database.KbDocVersion.id).where(database.KbDocVersion.doc_id == doc_id,
                                                                database.KbDocVersion.version == version)):
            raise ValueError('文件版本不存在')
        title = f'{file_label(doc)} · {version}'
    else:
        if job_id:
            job = db.get(database.IngestJob, job_id)
        else:
            library, project = body.get('library', ''), body.get('project', '')
            if not library or not project:
                raise ValueError('清理前请选择所属系统和工程，或选择一个文件')
            jobs = db.scalars(select(database.IngestJob).where(database.IngestJob.source_type == 'code_project',
                              database.IngestJob.status == 'done').order_by(database.IngestJob.created_at.desc()))
            job = next((j for j in jobs if j.options_json.get('library') == library and
                        j.options_json.get('project') == project and j.options_json.get('active') and
                        (not body.get('version') or j.options_json.get('version') == body['version'])), None)
        if not job or job.source_type != 'code_project' or job.status != 'done':
            raise ValueError('只支持清理已经完成的工程版本')
        docs = db.scalars(select(database.KbDocument).where(database.KbDocument.project_job == job.id)).all()
        version = ''  # The whole immutable snapshot, including legacy auxiliary versions.
        title = f'{job.options_json.get("project", "")} · {job.options_json.get("version", "")}'
    ids = {d.id for d in docs}
    chunks = db.scalars(select(database.KbDocChunk).where(database.KbDocChunk.doc_id.in_(ids))).all() if ids else []
    if version:
        chunks = [c for c in chunks if c.version == version]
    requested = set(body.get('chunk_ids') or [])
    if requested:
        if body['target'] != 'chunks' or not requested <= {c.id for c in chunks}:
            raise ValueError('切片不属于所选文件版本，或已被删除，请刷新后重试')
        chunks = [c for c in chunks if c.id in requested]
    graph = graphs.graph_store.dump()
    owned = (file_node_ids(docs[0], graph['nodes']) if doc_id else
             {n['id'] for n in graph['nodes'] if n['props'].get('project_job') == job.id})
    if doc_id and docs[0].asset_type != 'code' and version != docs[0].version:
        owned = set()  # Historical document versions do not have a live graph.
    nodes = [n for n in graph['nodes'] if n['id'] in owned] if body['target'] == 'graph' else []
    edges = [e for e in graph['edges'] if e['src'] in owned or e['dst'] in owned] if nodes else []
    vector_rows = {}
    if body['target'] == 'chunks':
        chunk_ids = {c.id for c in chunks}
        sources = {d.source_path for d in docs if d.source_path}
        for collection, entries in vectors.vector_store._data.items():
            vector_rows[collection] = [c for c in entries if c['id'] in chunk_ids or (not requested and
                ((c['meta'].get('doc_id') in ids and (not version or c['meta'].get('version') == version)) or
                 (c['meta'].get('source_path') in sources and (not version or c['meta'].get('version') == version))))]
    affected_chunks = chunks if body['target'] == 'chunks' else []
    counts = dict(files=len(docs), chunks=len(affected_chunks), vectors=sum(map(len, vector_rows.values())),
                  nodes=len(nodes), edges=len(edges))
    signature = dict(scope=body, chunks=sorted(c.id for c in affected_chunks), nodes=sorted(n['id'] for n in nodes),
                     edges=sorted((e['src'], e['rel'], e['dst']) for e in edges),
                     vectors={k: sorted(c['id'] for c in v) for k, v in vector_rows.items()})
    token = hashlib.sha256(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(title=title, counts=counts, token=token), docs, affected_chunks, nodes, edges, vector_rows


def preview(body):
    with _upload_lock, _lock, database.SessionLocal() as db:
        result, *_ = _selection(db, body)
        return result


def execute(body, token):
    with _upload_lock, _lock, database.SessionLocal() as db:
        result, docs, chunks, nodes, edges, entries = _selection(db, body)
        if not token or token != result['token']:
            raise ValueError('清理范围已变化，请重新查看清理预览并确认')
        nodes, edges, entries = deepcopy(nodes), deepcopy(edges), deepcopy(entries)
        try:
            if body['target'] == 'chunks':
                for collection, rows in entries.items():
                    vectors.vector_store.delete_ids(collection, {c['id'] for c in rows})
                for chunk in chunks:
                    db.delete(chunk)
                db.flush()
                for doc in docs:
                    exists = db.scalar(select(database.KbDocChunk.id).where(database.KbDocChunk.doc_id == doc.id,
                                       database.KbDocChunk.version == doc.version).limit(1))
                    doc.vectorized = int(bool(exists))
            else:
                graphs.graph_store.delete_nodes({n['id'] for n in nodes})
            for job_id in {d.project_job for d in docs if d.project_job}:
                job = db.get(database.IngestJob, job_id)
                job.options_json = {**job.options_json, 'cleaned_' + body['target']: True}
            graphs.graph_store.save()
            vectors.vector_store.save()
            db.commit()
        except Exception:
            db.rollback()
            for node in nodes:
                graphs.graph_store.upsert_node(node['id'], node['label'], node['props'])
            for edge in edges:
                graphs.graph_store.upsert_edge(edge['src'], edge['rel'], edge['dst'], edge['props'])
            for collection, rows in entries.items():
                for row in rows:
                    vectors.vector_store.upsert(collection, row['id'], row['vector'], row['meta'])
            graphs.graph_store.save()
            vectors.vector_store.save()
            raise
        return result
