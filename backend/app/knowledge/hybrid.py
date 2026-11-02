"""Identifier-scoped BM25 + optional semantic recall + exact source context."""
from pathlib import PurePosixPath
import re

from sqlalchemy import select

from .. import db as database
from ..llm import get_embedder, get_reranker
from ..llm.base import HashEmbedder
from . import lexical
from .catalog import current_project_jobs


def code_scope(query, graph, current, rows):
    """None means unspecified; an empty set means an explicitly missing filename."""
    direct = lexical.identifiers(lexical.current_question(query))
    aliases = {}
    for node in graph.dump()['nodes']:
        props = node['props']
        if props.get('project_job') and props['project_job'] not in current:
            continue
        if node['label'] == 'CodeFile' or props.get('kind') == 'module':
            path = props.get('source_path')
            if path:
                aliases.setdefault(path, set()).add(props.get('name', '').upper())
    with database.SessionLocal() as db:
        docs = db.scalars(select(database.KbDocument).where(database.KbDocument.asset_type == 'code',
            database.KbDocument.is_current == 1, database.KbDocument.vectorized == 1)).all()
        docs = [d for d in docs if not d.project_job or d.project_job in current]
        for doc in docs:
            aliases.setdefault(doc.source_path, set()).update({PurePosixPath(doc.source_path).name.upper(), PurePosixPath(doc.source_path).stem.upper()})
        for row in rows:
            path = row['meta'].get('source_path', '')
            aliases.setdefault(path, set()).update({PurePosixPath(path).name.upper(), PurePosixPath(path).stem.upper()})
        file_paths = {path for path in aliases if direct & {PurePosixPath(path).name.upper(), PurePosixPath(path).stem.upper()}}
        paths = file_paths or {path for path, names in aliases.items() if direct & names}
        if not paths and not direct:
            inherited = lexical.identifiers(query)
            paths = {path for path, names in aliases.items() if inherited & names}
        # A named project/system disambiguates same-named programs without guessing.
        matching_projects = {d.project for d in docs if d.project and re.search(r'(?<![A-Za-z0-9_-])' + re.escape(d.project) + r'(?![A-Za-z0-9_-])', lexical.current_question(query), re.I)}
        if paths and matching_projects:
            paths &= {d.source_path for d in docs if d.project in matching_projects}
            if not paths:
                return set(), []
        systems = db.scalars(select(database.KbLibrary)).all()
        matching_libraries = {system.key for system in systems if system.title and system.title in lexical.current_question(query)}
        if paths and matching_libraries:
            paths &= {d.source_path for d in docs if d.library_key in matching_libraries}
            if not paths:
                return set(), []
        selected = [d for d in docs if d.source_path in paths]
        if paths:
            return paths, selected
        if re.search(r'(?<![\w-])[\w-]+\.(?:cbl|cob|cpy)(?![\w-])', lexical.current_question(query), re.I):
            return set(), []
        return None, []


def _evidence(row, channel, query, score, rank):
    meta = row['meta']; text = meta.get('text', ''); loc = meta.get('loc', '')
    if channel == 'code':
        match = re.match(r'L(\d+)', loc)
        text, begin, end = lexical.focus(query, text, int(match[1]) if match else 1)
        if match:
            loc = f'L{begin}-L{end}'
    return dict(channel=channel, kind='chunk', chunk_id=row['id'],
        ref=meta.get('title') or meta.get('code_unit') or meta.get('business_key') or row['id'],
        label=meta.get('source_path', ''), obj=meta.get('source_path', ''), loc=loc, text=text,
        score=score / (score + 6), lexical_score=score, recall_score=1 / (60 + rank),
        project=meta.get('project', ''), library=meta.get('library', ''), version=meta.get('version', ''))


def source_context(query, docs):
    out = []
    requested = lexical.identifiers(lexical.current_question(query))
    with database.SessionLocal() as db:
        for doc in docs[:8]:
            job = db.get(database.IngestJob, doc.project_job) if doc.project_job else None
            if job and job.options_json.get('cleaned_chunks'):
                continue  # Do not bypass an explicit cleanup, including partial cleanup.
            version = db.scalar(select(database.KbDocVersion).where(database.KbDocVersion.doc_id == doc.id,
                                                                     database.KbDocVersion.version == doc.version))
            if not version:
                continue
            content = version.content; start = 1
            # A named paragraph stays in its own range instead of finding a CALL elsewhere.
            chunks = db.scalars(select(database.KbDocChunk).where(database.KbDocChunk.doc_id == doc.id,
                database.KbDocChunk.version == doc.version)).all()
            named = sorted([c for c in chunks if c.title.upper() in requested],
                           key=lambda c: (c.meta_json.get('kind') != 'function', -len(c.title)))
            if named:
                chunk = named[0]; content = chunk.text
                match = re.match(r'L(\d+)', chunk.meta_json.get('loc', ''))
                start = chunk.meta_json.get('start_line') or (int(match[1]) if match else version.content[:chunk.start_offset].count('\n') + 1)
            # A file name alone is only enough to show source; it cannot prove an operation.
            text, begin, end = lexical.focus(query, content, start)
            out.append(dict(channel='code', kind='source_context', ref=(named[0].title if named else PurePosixPath(doc.source_path).name),
                label=doc.source_path, obj=doc.source_path, loc=f'L{begin}-L{end}', text=text,
                project=doc.project, library=doc.library_key, version=doc.version,
                score=1.0, recall_score=1 / 60, source_context=True))
    return out


def search(query, collections, top_k, store, graph):
    current = current_project_jobs(); indexes = {col: lexical.index_for(store, col, current) for col in collections}
    code_rows = indexes['kb_code_chunk'].rows if 'kb_code_chunk' in indexes else []
    paths, docs = code_scope(query, graph, current, code_rows)
    requested = lexical.identifiers(lexical.current_question(query))
    subjects = {PurePosixPath(doc.source_path).stem.upper() for doc in docs
                if requested & {PurePosixPath(doc.source_path).name.upper(), PurePosixPath(doc.source_path).stem.upper()}}
    if not subjects:
        subjects = {node['props'].get('name', '').upper() for node in graph.dump()['nodes']
                    if node['props'].get('kind') == 'module' and node['props'].get('source_path') in (paths or set())
                    and node['props'].get('name', '').upper() in requested}
    if len({(doc.library_key, doc.project) for doc in docs}) > 1 and len(subjects) == 1:
        return [dict(channel='code', kind='ambiguous_scope', ref=PurePosixPath(doc.source_path).name,
            label=doc.source_path, obj=doc.source_path, loc='', score=1,
            text=f'同名文件位于系统 {doc.library_key} / 工程 {doc.project} / 版本 {doc.version}，请补充系统或工程名称后定位。') for doc in docs[:top_k]]
    candidates = []
    for collection, index in indexes.items():
        channel = 'doc' if collection == 'kb_doc_chunk' else 'code' if collection == 'kb_code_chunk' else 'mapping'
        # Filter before top-k so unrelated files cannot crowd out the requested program.
        matched = index.search(query, limit=len(index.rows) if paths is not None and channel == 'code' else max(30, top_k * 4))
        for rank, (row, score) in enumerate(matched, 1):
            if paths is not None and channel == 'code' and row['meta'].get('source_path') not in paths:
                continue
            query_ids = lexical.identifiers(lexical.current_question(query))
            meta = row['meta']
            if query_ids and not query_ids & lexical.identifiers(' '.join(str(meta.get(key, '')) for key in ('text', 'title', 'code_unit', 'source_path'))):
                continue
            candidates.append(_evidence(row, channel, query, score, rank))
    if 'kb_code_chunk' in collections:
        candidates.extend(source_context(query, docs))
    embedder = get_embedder()
    # Hash collisions are not semantic evidence. With no model, BM25 is the recall channel.
    compatible = any(row['meta'].get('embedding') == embedder.name for index in indexes.values() for row in index.rows)
    if not isinstance(embedder, HashEmbedder) and compatible:
        try:
            query_vector = embedder.embed([query])[0]
            for collection in collections:
                channel = 'doc' if collection == 'kb_doc_chunk' else 'code' if collection == 'kb_code_chunk' else 'mapping'
                for rank, hit in enumerate(store.search(collection, query_vector, top_k=max(30, top_k * 4), meta_filter={'embedding': embedder.name}), 1):
                    if paths is not None and channel == 'code' and hit['meta'].get('source_path') not in paths:
                        continue
                    evidence = _evidence(hit, channel, query, 0, rank)
                    evidence.update(score=hit['score'], semantic=True)
                    candidates.append(evidence)
        except Exception:
            pass  # The lexical/source channels stay available when an optional service fails.
    return rank_evidence(query, candidates)[:top_k]


def rank_evidence(query, evidences):
    """Deduplicate by provenance; lexical/source relevance precedes graph summaries."""
    requested = lexical.identifiers(lexical.current_question(query)); words = set(lexical.terms(query))
    operations = lexical.actions(query); unique = {}
    for original in evidences:
        evidence = dict(original)
        text = evidence.get('text', '') or ''; path = evidence.get('obj') or evidence.get('path') or evidence.get('label', '')
        key = evidence.get('channel'), path, evidence.get('loc', ''), evidence.get('ref', '')
        if key in unique:
            unique[key]['recall_score'] = unique[key].get('recall_score', 0) + evidence.get('recall_score', 0)
            previous = unique[key]['_order']
            unique[key]['_order'] = (*previous[:4], unique[key]['recall_score'], previous[5])
            continue
        filename = PurePosixPath(path.replace('\\', '/'))
        file_match = bool(requested & {filename.name.upper(), filename.stem.upper()})
        section_match = evidence.get('channel') != 'graph' and str(evidence.get('ref', '')).upper() in requested
        overlap = len(words & set(lexical.terms(text + ' ' + str(evidence.get('ref', '')))))
        op_match = sum(bool(re.search(r'(?<![\w-])' + re.escape(op) + r'(?![\w-])', text.upper())) for op in operations)
        evidence['_order'] = (int(section_match), int(file_match), int(evidence.get('channel') == 'code' and op_match > 0),
            int(evidence.get('channel') != 'graph'), evidence.get('recall_score', 0), overlap)
        evidence['rank_score'] = evidence.get('score', 0)
        unique[key] = evidence
    result = sorted(unique.values(), key=lambda item: item['_order'], reverse=True)
    reranker = get_reranker()
    if reranker and result:
        try:
            scores = reranker.rerank(query, [e.get('text', '') for e in result])
            if len(scores) == len(result):
                for evidence, score in zip(result, scores):
                    evidence['rank_score'] = float(score)
                result.sort(key=lambda item: (*item['_order'][:3], item['rank_score']), reverse=True)
        except Exception:
            pass
    # A file contributes at most three passages; preserve different files/versions separately.
    out, counts, texts = [], {}, set()
    for evidence in result:
        path = evidence.get('obj') or evidence.get('path') or evidence.get('label', '')
        text_key = (evidence.get('channel'), path, re.sub(r'\s+', ' ', evidence.get('text', '')).strip())
        if counts.get(path, 0) >= 3 or text_key in texts:
            continue
        counts[path] = counts.get(path, 0) + 1; texts.add(text_key); evidence.pop('_order', None); out.append(evidence)
    return out[:12]
