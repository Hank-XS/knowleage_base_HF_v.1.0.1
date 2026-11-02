"""Shared classification and asset statistics for documents and code snapshots."""
from collections import Counter, defaultdict
import hashlib

from sqlalchemy import select, func

from ..db import SessionLocal, KbDocument, KbDocChunk, IngestJob
from ..ingest.documents import PURPOSES, normalize_tags


def classification(library, project='', purpose='reference', tags=None):
    library, project = library.strip(), project.strip()
    if not library or len(library) > 128:
        raise ValueError('请选择所属系统／知识库')
    if len(project) > 100:
        raise ValueError('工程名称不能超过 100 个字符')
    if purpose not in PURPOSES and purpose != 'source':
        raise ValueError('请选择有效的资料用途')
    return dict(library=library, project=project, purpose=purpose, tags=normalize_tags(tags or []))


def project_key(library, project):
    return hashlib.sha256(f'{library}\0{project}'.encode()).hexdigest()[:24]


def current_project_jobs():
    with SessionLocal() as db:
        jobs = db.scalars(select(IngestJob).where(IngestJob.source_type == 'code_project', IngestJob.status == 'done')
                          .order_by(IngestJob.created_at.desc())).all()
        selected = {}
        for job in jobs:
            opt = job.options_json
            identity = (opt.get('library'), opt.get('project'))
            if opt.get('active') and identity not in selected:
                selected[identity] = job.id
        return set(selected.values())


def classified_graph_nodes(nodes):
    """Read older graph snapshots with the classification recorded on their jobs."""
    missing = {n['props']['project_job'] for n in nodes
               if n['props'].get('project_job') and not n['props'].get('library')}
    if not missing:
        return nodes
    with SessionLocal() as db:
        metadata = {job.id: dict(library=job.options_json.get('library', ''),
                                tags=job.options_json.get('tags', []), purpose='source')
                    for job in db.scalars(select(IngestJob).where(IngestJob.id.in_(missing)))}
    return [{**n, 'props': {**metadata.get(n['props'].get('project_job'), {}), **n['props']}} for n in nodes]


def catalog_options(kb='', project=''):
    from .manage import library_tree
    with SessionLocal() as db:
        docs = db.scalars(select(KbDocument)).all()
        jobs = db.scalars(select(IngestJob).where(IngestJob.source_type == 'code_project')).all()
        projects = {(d.library_key, d.project) for d in docs if d.project}
        projects |= {(j.options_json.get('library', ''), j.options_json.get('project', '')) for j in jobs}
        scoped_docs = [d for d in docs if (not kb or d.library_key == kb or d.library_key.startswith(kb + '/')) and (not project or d.project == project)]
        tags = Counter(tag for d in scoped_docs if d.is_current and d.asset_type != 'code' for tag in (d.tags_json or []))
        current = current_project_jobs()
        for job in jobs:
            if job.id in current and (not kb or job.options_json.get('library') == kb or job.options_json.get('library', '').startswith(kb + '/')) and (not project or job.options_json.get('project') == project):
                tags.update(job.options_json.get('tags', []))
        return dict(libraries=library_tree(), projects=[dict(library=k, name=p) for k, p in sorted(projects) if k and p and (not kb or k == kb or k.startswith(kb + '/'))],
                    purposes=[dict(value=k, label=v) for k, v in PURPOSES.items()],
                    tags=[dict(value=t, count=n) for t, n in tags.most_common()])


def list_assets(kb='', project='', asset_type='', purpose='', tag='', keyword='',
                history=False, version='', page=1, page_size=20):
    from .manage import _doc_payload
    with SessionLocal() as db:
        docs = db.scalars(select(KbDocument)).all()
        chunk_counts = dict(db.execute(select(KbDocChunk.doc_id, func.count()).join(KbDocument, KbDocument.id == KbDocChunk.doc_id)
                                      .where(KbDocChunk.version == KbDocument.version)
                                      .group_by(KbDocChunk.doc_id)).all())
        jobs = db.scalars(select(IngestJob).where(IngestJob.source_type == 'code_project')
                          .order_by(IngestJob.created_at.desc())).all()
        newest = {}
        for job in jobs:
            opt = job.options_json
            key = (opt.get('library'), opt.get('project'))
            if job.status == 'done' and opt.get('active') and key not in newest:
                newest[key] = job.id
        rows, seen_pending = [], set()
        files_by_job = defaultdict(list)
        for doc in docs:
            if doc.project_job:
                files_by_job[doc.project_job].append(doc)
        attempts = {}
        for job in jobs:
            attempts.setdefault((job.options_json.get('library'), job.options_json.get('project')), job)
        for job in jobs:
            opt = job.options_json
            identity = (opt.get('library'), opt.get('project'))
            current = newest.get(identity) == job.id
            if not history:
                if newest.get(identity) and not current:
                    continue
                if not newest.get(identity) and identity in seen_pending:
                    continue
                seen_pending.add(identity)
            files = files_by_job[job.id]
            attempt = attempts[identity]
            rows.append(dict(id=job.id, asset_type='project', name=opt.get('project', ''),
                             library=opt.get('library', ''), project=opt.get('project', ''), purpose='source',
                             version=opt.get('version', ''), tags=opt.get('tags', []), status=job.status,
                             error=job.error or '', is_current=current, file_count=len(files),
                             attempt_status=attempt.status if attempt.id != job.id else '',
                             attempt_error=attempt.error or '', attempt_version=attempt.options_json.get('version', ''),
                             chunk_count=sum(chunk_counts.get(d.id, 0) for d in files),
                             program_count=sum(d.doc_type.lower() in {'cbl', 'cob', 'cobol'} for d in files),
                             copybook_count=sum(d.doc_type.lower() == 'cpy' for d in files),
                             uploadedAt=job.created_at.isoformat(), warnings=opt.get('summary', {}).get('warnings', 0)))
        for doc in docs:
            if doc.asset_type == 'code':
                continue
            if not history and not doc.is_current:
                continue
            rows.append({**_doc_payload(doc), 'asset_type': 'document', 'library': doc.library_key,
                         'file_count': 1, 'chunk_count': chunk_counts.get(doc.id, 0)})
        def match(row):
            return ((not kb or row['library'] == kb or row['library'].startswith(kb + '/'))
                    and (not project or row['project'] == project)
                    and (not asset_type or row['asset_type'] == asset_type)
                    and (not purpose or row['purpose'] == purpose)
                    and (not tag or tag in row['tags'])
                    and (not version or row['version'] == version)
                    and (not keyword or keyword.casefold() in (row['name'] + ' ' + row['project'] + ' ' + ' '.join(row['tags'])).casefold()))
        rows = sorted((r for r in rows if match(r)), key=lambda r: r['uploadedAt'], reverse=True)
        stats = dict(projects=sum(r['asset_type'] == 'project' for r in rows),
                     documents=sum(r['asset_type'] == 'document' for r in rows),
                     files=sum(r['file_count'] for r in rows), chunks=sum(r['chunk_count'] for r in rows))
        first = (page - 1) * page_size
        return dict(items=rows[first:first + page_size], total=len(rows), stats=stats)
