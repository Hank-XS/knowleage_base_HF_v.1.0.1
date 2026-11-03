"""Build complete retrieval generations from an immutable source manifest, then activate."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from sqlalchemy import select

from .. import db as database
from ..config import DATA_DIR
from ..stores.vector import COLLECTIONS
from .representations import encode_many, file_overview


def corpus_manifest():
    from .catalog import current_project_jobs
    current = current_project_jobs()
    with database.SessionLocal() as db:
        docs = db.scalars(select(database.KbDocument).where(database.KbDocument.is_current == 1,
            database.KbDocument.vectorized == 1)).all()
        output = []
        for doc in docs:
            if doc.project_job and doc.project_job not in current:
                continue
            body = db.scalar(select(database.KbDocVersion.content).where(database.KbDocVersion.doc_id == doc.id,
                database.KbDocVersion.version == doc.version)) or ''
            chunks = db.scalars(select(database.KbDocChunk).where(database.KbDocChunk.doc_id == doc.id,
                database.KbDocChunk.version == doc.version).order_by(database.KbDocChunk.id)).all()
            chunk_digest = hashlib.sha256(json.dumps([(c.id,c.start_offset,c.end_offset,c.text) for c in chunks],ensure_ascii=False).encode()).hexdigest()
            output.append(dict(id=doc.id, version=doc.version, path=doc.source_path, security=doc.security,author=doc.author,
                chunks_sha256=chunk_digest,
                sha256=hashlib.sha256(body.encode()).hexdigest()))
    return sorted(output, key=lambda d:d['id'])


def rebuild(store, embedder, progress=None, stage_only=False):
    started = time.monotonic()
    manifest = corpus_manifest()
    expected_revision = store.revision
    generation = uuid.uuid4().hex
    output = {collection:[] for collection in COLLECTIONS}
    with database.SessionLocal() as db:
        for i, item in enumerate(manifest):
            doc = db.get(database.KbDocument, item['id'])
            body = db.scalar(select(database.KbDocVersion.content).where(database.KbDocVersion.doc_id == doc.id,
                database.KbDocVersion.version == doc.version))
            chunks = db.scalars(select(database.KbDocChunk).where(database.KbDocChunk.doc_id == doc.id,
                database.KbDocChunk.version == doc.version).order_by(database.KbDocChunk.chunk_index)).all()
            collection = 'kb_code_chunk' if doc.asset_type == 'code' else 'kb_doc_chunk'
            parents = []
            for chunk in chunks:
                line = body[:chunk.start_offset].count('\n') + 1
                meta = {**chunk.meta_json, 'doc_id':doc.id, 'project_job':doc.project_job,
                    'project':doc.project, 'library':doc.library_key, 'version':doc.version,
                    'source_path':doc.source_path, 'title':chunk.title, 'code_unit':chunk.title,
                    'loc':f'L{line}-L{line + len(chunk.text.splitlines()) - 1}',
                    'text':chunk.text, 'security':doc.security, 'author':doc.author,
                    'generation_id':generation, 'source_hash':item['sha256'],
                    'channel':'code' if doc.asset_type == 'code' else 'doc'}
                job = db.get(database.IngestJob,doc.project_job) if doc.project_job else None
                if not parents and doc.asset_type == 'code' and not (job and job.options_json.get('cleaned_chunks')):
                    meta['file_overview'] = file_overview(body,doc.source_path)
                parents.append((chunk.id, chunk.text, meta))
            prepared = encode_many(parents, embedder)
            for chunk, (vector, indexed) in zip(chunks, prepared):
                output[collection].append(dict(id=chunk.id, vector=vector, meta=indexed))
            if progress:
                progress(dict(completed=i+1,total=len(manifest),chunks=sum(map(len,output.values()))))
    if corpus_manifest() != manifest:
        raise ValueError('构建期间资料或权限已变化；新索引未激活，请重新构建')
    root = DATA_DIR / 'runtime' / 'index-generations'
    root.mkdir(parents=True, exist_ok=True)
    # Include all storage collections, including legacy mapping material not in the catalog.
    output['kb_mapping_chunk'] = store.export('kb_mapping_chunk')
    backup = root / f'before-{generation}.json'
    backup.write_text(json.dumps({**{c:store.export(c) for c in COLLECTIONS},'__manifest':store.manifest}, ensure_ascii=False), encoding='utf-8')
    report = dict(generation_id=generation, embedding_space=embedder.name, corpus=manifest,
        parents=sum(map(len,output.values())), children=sum(len(r['meta'].get('children',[])) for rows in output.values() for r in rows),
        elapsed_seconds=round(time.monotonic()-started,2), rollback_file=str(backup), status='validated')
    staged = root / f'{generation}.json'
    staged.write_text(json.dumps(output, ensure_ascii=False),encoding='utf-8')
    # Persist the manifest before publishing; only successful activation receives active status.
    report_path = root / f'{generation}.manifest.json'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not stage_only:
        store.replace_all(output, expected_revision=expected_revision,manifest=dict(generation_id=generation,embedding_space=embedder.name))
        report['status'] = 'active'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def activate(store, generation):
    if not generation or any(c not in '0123456789abcdef' for c in generation):
        raise ValueError('Invalid generation')
    root = DATA_DIR / 'runtime/index-generations'
    report_path = root / f'{generation}.manifest.json'
    report = json.loads(report_path.read_text('utf-8'))
    if corpus_manifest() != report['corpus']:
        raise ValueError('资料或权限已变化，禁止激活过期索引')
    store.replace_all(json.loads((root / f'{generation}.json').read_text('utf-8')),
        manifest=dict(generation_id=generation,embedding_space=report['embedding_space']))
    report['status'] = 'active'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def rollback(store, generation):
    if not generation or any(c not in '0123456789abcdef' for c in generation):
        raise ValueError('Invalid generation')
    root = DATA_DIR / 'runtime/index-generations'
    report = json.loads((root / f'{generation}.manifest.json').read_text('utf-8'))
    if report['corpus'] != corpus_manifest():
        raise ValueError('资料已变化，回滚会恢复过期或已撤权知识，已拒绝；请重新构建')
    store.replace_all(json.loads((root / f'before-{generation}.json').read_text('utf-8')))
    report['status'] = 'rolled_back'
    (root / f'{generation}.manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
