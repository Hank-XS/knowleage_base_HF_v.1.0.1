"""File identity, real uploaded versions, and document/code reference browsing."""
from difflib import SequenceMatcher
from pathlib import PurePosixPath
import re

from sqlalchemy import select

from .. import db as database


def relative_source(doc):
    prefix = f'kb-raw/projects/{doc.project_job}/source/'
    source = (doc.source_path or doc.path).replace('\\', '/')
    return source[len(prefix):] if source.startswith(prefix) else source


def identity(doc):
    return doc.library_key, doc.project, doc.asset_type, relative_source(doc) if doc.asset_type == 'code' else doc.path


def file_label(doc):
    suffix = '.' + doc.doc_type
    return doc.name if doc.name.lower().endswith(suffix.lower()) else doc.name + suffix


def _version_rows(db, doc):
    if doc.asset_type != 'code' or not doc.project_job:
        return [(doc, v) for v in db.scalars(select(database.KbDocVersion)
                .where(database.KbDocVersion.doc_id == doc.id).order_by(database.KbDocVersion.created_at))]
    jobs = {j.id: j for j in db.scalars(select(database.IngestJob).where(
        database.IngestJob.source_type == 'code_project', database.IngestJob.status == 'done'))}
    candidates = db.scalars(select(database.KbDocument).where(
        database.KbDocument.library_key == doc.library_key, database.KbDocument.project == doc.project,
        database.KbDocument.asset_type == 'code',
        database.KbDocument.source_path.endswith('/source/' + relative_source(doc), autoescape=True))
        .order_by(database.KbDocument.uploaded_at.desc())).all()
    selected, seen = [], set()
    for candidate in candidates:
        job = jobs.get(candidate.project_job)
        if not job or not job.options_json.get('active') or identity(candidate) != identity(doc):
            continue
        version = job.options_json.get('version', candidate.version)
        row = db.scalar(select(database.KbDocVersion).where(database.KbDocVersion.doc_id == candidate.id,
                                                           database.KbDocVersion.version == version))
        if row and version not in seen:
            selected.append((candidate, row))
            seen.add(version)
    return sorted(selected, key=lambda pair: pair[0].uploaded_at)


def comparison_versions(doc_id):
    with database.SessionLocal() as db:
        doc = db.get(database.KbDocument, doc_id)
        if not doc:
            raise ValueError('文件不存在')
        return [dict(id=v.id, doc_id=d.id, version=v.version, created_at=v.created_at.isoformat(),
                     project_job=d.project_job, current=bool(d.is_current and (d.asset_type == 'code' or v.version == d.version)))
                for d, v in _version_rows(db, doc)]


def _resolve_version(db, doc, version_id=''):
    rows = _version_rows(db, doc)
    if version_id:
        found = next(((d, v) for d, v in rows if v.id == version_id), None)
    else:
        found = next(((d, v) for d, v in reversed(rows) if d.is_current), None) or (rows[-1] if rows else None)
    if not found:
        raise ValueError('该文件版本不存在或已被替换，请重新选择')
    return found


def compare(doc_id, old_id, new_id):
    from .manage import _doc_payload
    with database.SessionLocal() as db:
        doc = db.get(database.KbDocument, doc_id)
        if not doc:
            raise ValueError('文件不存在')
        _, old = _resolve_version(db, doc, old_id)
        _, new = _resolve_version(db, doc, new_id)
        a, b = old.content.splitlines(), new.content.splitlines()
        rows, stats = [], dict(added=0, removed=0, modified=0)
        for operation, i, j, k, m in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            left, right = a[i:j], b[k:m]
            for index in range(max(len(left), len(right))):
                l = left[index] if index < len(left) else None
                r = right[index] if index < len(right) else None
                kind = 'same' if operation == 'equal' else 'add' if l is None else 'del' if r is None else 'mod'
                if kind != 'same':
                    stats[{'add': 'added', 'del': 'removed', 'mod': 'modified'}[kind]] += 1
                rows.append(dict(left=l, right=r, type=kind))
        return dict(doc=_doc_payload(doc), old=old.version, new=new.version, rows=rows, stats=stats,
                    old_content=old.content, new_content=new.content)


def project_versions(library='', project=''):
    with database.SessionLocal() as db:
        jobs = db.scalars(select(database.IngestJob).where(database.IngestJob.source_type == 'code_project',
                          database.IngestJob.status == 'done').order_by(database.IngestJob.created_at.desc()))
        values = []
        for job in jobs:
            p = job.options_json
            if p.get('active') and (not library or p.get('library') == library) and (not project or p.get('project') == project):
                values.append(dict(id=job.id, version=p.get('version', ''), project=p.get('project', ''), library=p.get('library', '')))
        return values


def _symbol(doc, content):
    program = re.search(r'\bPROGRAM-ID\.\s*([A-Z0-9_-]+)', content, re.I)
    return (program.group(1) if program else PurePosixPath(doc.name).stem).upper()


def _reference(body, symbol):
    if not symbol or len(symbol) < 2:
        return ''
    pattern = re.compile(r'(?<![A-Z0-9_-])' + re.escape(symbol) + r'(?![A-Z0-9_-])', re.I)
    return next((line.strip()[:240] for line in body.splitlines() if pattern.search(line)), '')


def code_map(doc_id, direction='code2doc', version_id=''):
    with database.SessionLocal() as db:
        original = db.get(database.KbDocument, doc_id)
        if not original:
            raise ValueError('文件不存在')
        doc, version = _resolve_version(db, original, version_id)
        is_code = doc.asset_type == 'code' or doc.doc_type in {'cbl', 'cob', 'cobol', 'cpy', 'java', 'py', 'sql', 'jcl'}
        if (direction == 'code2doc') != is_code:
            raise ValueError('请按映射方向选择代码文件或文档')
        query = select(database.KbDocument).where(database.KbDocument.library_key == doc.library_key,
                                                 database.KbDocument.is_current == 1, database.KbDocument.id != doc.id)
        if direction == 'code2doc':
            query = query.where(database.KbDocument.asset_type == 'document',
                                 database.KbDocument.doc_type.in_({'md', 'docx', 'pdf', 'txt'}))
            if doc.project:
                query = query.where(database.KbDocument.project.in_([doc.project, '']))
        else:
            query = query.where(database.KbDocument.asset_type == 'code')
            if doc.project:
                query = query.where(database.KbDocument.project == doc.project)
        candidates = db.scalars(query.order_by(database.KbDocument.name)).all()
        ids = [candidate.id for candidate in candidates]
        contents = {(v.doc_id, v.version): v for v in db.scalars(select(database.KbDocVersion)
                    .where(database.KbDocVersion.doc_id.in_(ids)))} if ids else {}
        related, symbol = [], _symbol(doc, version.content) if is_code else ''
        for candidate in candidates:
            row = contents.get((candidate.id, candidate.version))
            if not row:
                continue
            candidate_symbol = symbol if is_code else _symbol(candidate, row.content)
            snippet = _reference((row.content + '\n' + candidate.name) if is_code else version.content, candidate_symbol)
            if snippet:
                related.append(dict(id=candidate.id, name=file_label(candidate), section=snippet,
                                    version=row.version, version_id=row.id, project=candidate.project))
        return dict(file=dict(key=doc.id, label=file_label(doc), version=version.version, kb=doc.library_key,
                              project=doc.project, content=version.content),
                    relatedDocs=related, symbol=symbol, direction=direction, match_method='symbol_reference')
