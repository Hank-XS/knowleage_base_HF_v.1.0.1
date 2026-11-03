"""Document visibility shared by RAG retrieval, context expansion and source previews."""
from sqlalchemy import select
from .. import db as database


def denied_paths(username, role=''):
    if role == 'admin':
        return set()
    with database.SessionLocal() as db:
        docs = db.scalars(select(database.KbDocument)).all()
        denied = set()
        for doc in docs:
            level = (doc.security or 'internal').lower()
            visible = level in {'public', 'internal'} or doc.author == username
            if level in {'restricted', 'confidential'} and role in {'gov', 'arch'}:
                visible = True
            if not visible:
                denied.update({doc.source_path, doc.object_key, doc.path})
                denied.update(db.scalars(select(database.KbDocVersion.object_key).where(database.KbDocVersion.doc_id == doc.id)).all())
        return denied - {''}


def readable_document(doc_id: str, user=None):
    # Called through the explicit FastAPI dependency below, not from indexing jobs.
    from ..response import KbError
    with database.SessionLocal() as db:
        doc = db.get(database.KbDocument, doc_id)
        if doc is None:
            raise KbError('40401', '文件不存在')
        if doc.source_path in denied_paths(user.username, user.role):
            raise KbError('40301', '该资料不可访问')
