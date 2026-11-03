"""Identifier-scoped BM25 + optional semantic recall + exact source context."""
from pathlib import PurePosixPath
from functools import lru_cache
import re
import math
import time

from sqlalchemy import select

from .. import db as database
from ..config import settings
from ..llm import get_embedder, get_reranker
from ..llm.base import HashEmbedder
from . import lexical
from .catalog import current_project_jobs
from .evidence import normalize, duplicate
from .scope import active_scope
from .query_parser import parse_query, code_match, code_tokens, find_tokens


def code_scope(query, graph, current, rows):
    """None means unspecified; an empty set means an explicitly missing filename."""
    plan = parse_query(lexical.current_question(query))
    scoped_query = plan.scope_query if plan.code or plan.mode == 'similar' else lexical.current_question(query)
    constraint_query = plan.narrative if plan.code else lexical.current_question(query)
    direct = set() if plan.mode == 'similar' else lexical.identifiers(scoped_query)
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
        relative_names = re.findall(r'(?:[\w.-]+/)+[\w.-]+\.(?:cbl|cob|cpy)', scoped_query, re.I)
        precise = {path for path in file_paths if any(path.lower().endswith('/' + name.lower()) for name in relative_names)}
        file_paths = precise or file_paths
        paths = file_paths or {path for path, names in aliases.items() if direct & names}
        if not paths and not direct and not plan.code and plan.mode != 'similar':
            inherited = lexical.identifiers(query)
            paths = {path for path, names in aliases.items() if inherited & names}
        if not paths and re.search(r'(?<![\w-])[\w-]+\.(?:cbl|cob|cpy)(?![\w-])', scoped_query, re.I):
            return set(), []
        # A named project/system disambiguates same-named programs without guessing.
        matching_projects = {d.project for d in docs if d.project and re.search(r'(?<![A-Za-z0-9_-])' + re.escape(d.project) + r'(?![A-Za-z0-9_-])', constraint_query, re.I)}
        if matching_projects:
            project_paths = {d.source_path for d in docs if d.project in matching_projects}
            paths = paths & project_paths if paths else project_paths
            if not paths:
                return set(), []
        systems = db.scalars(select(database.KbLibrary)).all()
        matching_libraries = {system.key for system in systems if system.title and system.title in constraint_query}
        if matching_libraries:
            library_paths = {d.source_path for d in docs if d.library_key in matching_libraries}
            paths = paths & library_paths if paths else library_paths
            if not paths:
                return set(), []
        selected = [d for d in docs if d.source_path in paths]
        if paths:
            return paths, selected
        if re.search(r'(?<![\w-])[\w-]+\.(?:cbl|cob|cpy)(?![\w-])', scoped_query, re.I):
            return set(), []
        return None, []


def _evidence(row, channel, query, score, rank):
    meta = row['meta']; text = meta.get('text', ''); loc = meta.get('loc', '')
    if channel == 'code':
        match = re.fullmatch(r'L(\d+)(?:-L?\d+)?', loc)
        text, begin, end = lexical.focus(query, text, int(match[1]) if match else 1)
        if match:
            loc = f'L{begin}-L{end}'
    return dict(channel=channel, kind='chunk', chunk_id=row['id'], parent_id=meta.get('parent_id'),
        ref=meta.get('title') or meta.get('code_unit') or meta.get('business_key') or row['id'],
        label=meta.get('source_path', ''), obj=meta.get('source_path', ''), loc=loc, text=text,
        score=score / (score + 6), lexical_score=score, recall_score=1 / (60 + rank),
        retrieval_channels={'lexical':1/(60+rank)},
        project=meta.get('project', ''), library=meta.get('library', ''), version=meta.get('version', ''),
        context_partial=meta.get('context_partial', False))


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
            # Module chunks start at IDENTIFICATION DIVISION and omit the file's
            # purpose comments. For overview questions keep the original header.
            module_only = bool(named and re.search(r'\bPROGRAM-ID\.\s*' + re.escape(named[0].title) + r'(?![\w-])', version.content, re.I))
            if named and not module_only and not (lexical.overview(query) and named[0].meta_json.get('kind') != 'function'):
                chunk = named[0]; content = chunk.text
                match = re.match(r'L(\d+)', chunk.meta_json.get('loc', ''))
                start = chunk.meta_json.get('start_line') or (int(match[1]) if match else version.content[:chunk.start_offset].count('\n') + 1)
            # A file name alone is only enough to show source; it cannot prove an operation.
            text, begin, end = lexical.focus(query, content, start)
            out.append(dict(channel='code', kind='source_context', ref=(named[0].title if named else PurePosixPath(doc.source_path).name),
                label=doc.source_path, obj=doc.source_path, loc=f'L{begin}-L{end}', text=text,
                project=doc.project, library=doc.library_key, version=doc.version,
                score=1.0, recall_score=1 / 60, source_context=True,
                focus_title=named[0].title if named and named[0].meta_json.get('kind') == 'function' else ''))
    return out


def search(query, collections, top_k, store, graph, *, rerank=True):
    current = current_project_jobs()
    scope = active_scope()
    indexes = {col: lexical.index_for(store, col, current, scope.denied_paths if scope else None) for col in collections}
    code_rows = indexes['kb_code_chunk'].rows if 'kb_code_chunk' in indexes else []
    paths, docs = code_scope(query, graph, current, code_rows)
    scope = active_scope()
    plan = scope.plan if scope and scope.plan else parse_query(query)
    original_query = query
    if scope:
        # A tool rewrite may refine the task, but cannot silently switch programs.
        if scope.paths is not None:
            paths, docs = scope.paths, scope.docs
        query = scope.question if query == scope.question else scope.question + '\n补充检索：' + query
    requested = lexical.identifiers(lexical.current_question(query))
    subjects = {PurePosixPath(doc.source_path).stem.upper() for doc in docs
                if requested & {PurePosixPath(doc.source_path).name.upper(), PurePosixPath(doc.source_path).stem.upper()}}
    if not subjects:
        subjects = {node['props'].get('name', '').upper() for node in graph.dump()['nodes']
                    if node['props'].get('kind') == 'module' and node['props'].get('source_path') in (paths or set())
                    and node['props'].get('name', '').upper() in requested}
    if len({doc.source_path for doc in docs}) > 1 and len(subjects) == 1:
        return [dict(channel='code', kind='ambiguous_scope', ref=PurePosixPath(doc.source_path).name,
            label=doc.source_path, obj=doc.source_path, loc='', score=1,
            project=doc.project, library=doc.library_key, version=doc.version,
            text=f'同名文件位于系统 {doc.library_key} / 工程 {doc.project} / 版本 {doc.version}，请补充系统或工程名称后定位。') for doc in docs[:top_k]]
    candidates = []
    contexts = source_context(query, docs) if 'kb_code_chunk' in collections else []
    if scope:
        contexts = [e for e in contexts if scope.allows(e.get('obj', ''))]
    for context in contexts:
        if scope:
            scope.learn(context)
    for collection, index in indexes.items():
        channel = 'doc' if collection == 'kb_doc_chunk' else 'code' if collection == 'kb_code_chunk' else 'mapping'
        # Filter before top-k so unrelated files cannot crowd out the requested program.
        matched = index.search(query, limit=len(index.rows) if paths is not None and channel == 'code' else max(30, top_k * 4))
        for rank, (row, score) in enumerate(matched, 1):
            if scope and not scope.allows(row['meta'].get('source_path', '')):
                continue
            if paths is not None and channel == 'code' and row['meta'].get('source_path') not in paths and not (scope and row['meta'].get('source_path') in scope.evidence_paths):
                if not (scope and scope.paths and scope.related_definition(original_query, row['meta'].get('source_path', ''),
                        row['meta'].get('text', ''), row['meta'].get('project_job', ''))):
                    continue
            query_ids = lexical.identifiers(lexical.current_question(query))
            meta = row['meta']
            if query_ids and not plan.code and plan.mode != 'similar' and not query_ids & lexical.identifiers(' '.join(str(meta.get(key, '')) for key in ('text', 'title', 'code_unit', 'source_path'))):
                continue
            candidates.append(_evidence(row, channel, query, score, rank))
    if 'kb_code_chunk' in collections:
        candidates.extend(contexts)
        if plan.code:
            candidates.extend(_snippet_evidence(plan, paths, current))
    exact_located = plan.mode == 'source' and any(e.get('relation_type') == 'exact_source' for e in candidates)
    embedder = None if exact_located else get_embedder()
    # Hash collisions are not semantic evidence. With no model, BM25 is the recall channel.
    compatible = embedder is not None and any(row['meta'].get('embedding') == embedder.name for index in indexes.values() for row in index.rows)
    if compatible and not isinstance(embedder, HashEmbedder):
        try:
            query_vector = (embedder.embed_queries([query]) if hasattr(embedder, 'embed_queries') else embedder.embed([query]))[0]
            for collection in collections:
                channel = 'doc' if collection == 'kb_doc_chunk' else 'code' if collection == 'kb_code_chunk' else 'mapping'
                for rank, hit in enumerate(store.search(collection, query_vector, top_k=max(30, top_k * 4), meta_filter={'embedding': embedder.name}, exclude_paths=scope.denied_paths if scope else None), 1):
                    if scope and not scope.allows(hit['meta'].get('source_path', '')):
                        continue
                    if paths is not None and channel == 'code' and hit['meta'].get('source_path') not in paths and not (scope and hit['meta'].get('source_path') in scope.evidence_paths):
                        if not (scope and scope.paths and scope.related_definition(original_query, hit['meta'].get('source_path', ''),
                                hit['meta'].get('text', ''), hit['meta'].get('project_job', ''))):
                            continue
                    evidence = _evidence(hit, channel, query, 0, rank)
                    evidence.update(score=hit['score'], semantic=True, recall_score=1/(60+rank),
                                    retrieval_channels={'semantic':1/(60+rank)})
                    candidates.append(evidence)
        except Exception:
            pass  # The lexical/source channels stay available when an optional service fails.
    candidates = [e for e in candidates if not scope or scope.allows(e.get('path') or e.get('obj') or e.get('label', ''))]
    ranked = rank_evidence(query, candidates, rerank=rerank, limit=top_k)
    if scope:
        scope.diagnostics.append(dict(tool='hybrid_recall', mode=plan.mode,
            lexical=sum(bool(e.get('lexical_score')) for e in candidates),
            semantic=sum(bool(e.get('semantic')) for e in candidates),
            source=sum(e.get('relation_type') == 'exact_source' for e in candidates),
            candidates=len(candidates), returned=len(ranked), rerank_pass=rerank))
    return ranked


@lru_cache(maxsize=128)
def _tokenized_source(body):
    tokens, positions = [], []
    for no, line in enumerate(body.splitlines(keepends=True)):
        part = code_tokens(line); tokens.extend(part); positions.extend([no] * len(part))
    return tokens, positions


def _snippet_evidence(plan, paths, current):
    """Match preserved source, including snippets crossing persistent chunk boundaries."""
    output = []
    needle = code_tokens(plan.code)
    if len(needle) < 3:
        return output
    with database.SessionLocal() as db:
        docs = db.scalars(select(database.KbDocument).where(database.KbDocument.asset_type == 'code',
            database.KbDocument.is_current == 1, database.KbDocument.vectorized == 1)).all()
        for doc in docs:
            scope = active_scope()
            if scope and not scope.allows(doc.source_path):
                continue
            if (doc.project_job and doc.project_job not in current) or (paths is not None and doc.source_path not in paths):
                continue
            job = db.get(database.IngestJob, doc.project_job) if doc.project_job else None
            if job and job.options_json.get('cleaned_chunks'):
                continue
            body = db.scalar(select(database.KbDocVersion.content).where(database.KbDocVersion.doc_id == doc.id,
                database.KbDocVersion.version == doc.version)) or ''
            lines = body.splitlines(keepends=True)
            tokens, positions = _tokenized_source(body)
            exact = find_tokens(tokens, needle)
            if exact is not None:
                begin = max(0, positions[exact] - 3); end = min(len(lines), positions[exact + len(needle) - 1] + 5)
                relation, score = 'exact_source', 1.0
            elif plan.mode == 'similar':
                best = (0.0, 0, 0)
                for first in range(0, len(lines), 8):
                    last = min(len(lines), first + max(16, min(60, len(plan.code.splitlines()) + 8)))
                    relation, similarity = code_match(plan.code, ''.join(lines[first:last]))
                    if similarity > best[0]:
                        best = similarity, first, last
                score, begin, end = best
                if score < .25:
                    continue
                relation = 'similar_logic'
            else:
                continue
            output.append(dict(channel='code', kind='source_context', ref=PurePosixPath(doc.source_path).name,
                path=doc.source_path, obj=doc.source_path, label=doc.source_path, loc=f'L{begin + 1}-L{end}',
                text=''.join(lines[begin:end]), version=doc.version, project=doc.project, library=doc.library_key,
                relation_type=relation, code_similarity=score, score=score, recall_score=1/59))
    return output


def rank_evidence(query, evidences, *, rerank=True, limit=12):
    """Deduplicate by provenance; lexical/source relevance precedes graph summaries."""
    requested = lexical.identifiers(lexical.current_question(query)); words = set(lexical.terms(query))
    operations = lexical.actions(query); unique = {}
    scope = active_scope()
    plan = scope.plan if scope and scope.plan else parse_query(query)
    weights = {'lexical':1.2 if plan.code else 1.0, 'semantic':1.5 if plan.mode == 'business' else 1.0, 'context':1.0}
    focused = {e.get('obj') or e.get('path'): e for e in evidences if e.get('focus_title')}
    for original in evidences:
        evidence = normalize(original)
        text = evidence.get('text', '') or ''; path = evidence.get('obj') or evidence.get('path') or evidence.get('label', '')
        target = focused.get(path)
        if target and evidence['channel'] == 'code' and not evidence.get('required_context') and not duplicate(normalize(target), evidence):
            anchors = requested - {PurePosixPath(path).name.upper(), PurePosixPath(path).stem.upper(), target['focus_title'].upper()}
            if target['focus_title'].upper() not in lexical.identifiers(text + ' ' + str(evidence.get('ref', ''))) and not anchors & lexical.identifiers(text):
                continue
        key = evidence.get('channel'), path, evidence.get('loc', ''), evidence.get('ref', '')
        channels = evidence.get('retrieval_channels') or {'context':evidence.get('recall_score', 0)}
        evidence['retrieval_channels'] = channels
        evidence['recall_score'] = sum(weights.get(name,1)*score for name,score in channels.items())
        if key in unique:
            merged = dict(unique[key]['retrieval_channels'])
            for name,score in channels.items():
                merged[name] = max(merged.get(name,0),score)
            unique[key]['retrieval_channels'] = merged
            unique[key]['recall_score'] = sum(weights.get(name,1)*score for name,score in merged.items())
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
    def order(item):
        if plan.code:
            return (int(item.get('relation_type') == 'exact_source'), item.get('code_similarity', 0), *item['_order'])
        if plan.mode == 'similar':
            return (int(item.get('channel') == 'code'), *item['_order'])
        return (*item['_order'][:2], item.get('recall_score', 0), *item['_order'][2:])
    result = sorted(unique.values(), key=order, reverse=True)
    located = plan.mode == 'source' and any(e.get('relation_type') == 'exact_source' for e in result)
    reranker = get_reranker() if rerank and result and not located else None
    if reranker and result and not located:
        started = time.monotonic()
        diagnostic = dict(tool='rerank', candidates=0, computed=0)
        try:
            # Apply diversity before expensive inference, not just after it.
            shortlist, counts = [], {}
            for item in result:
                path = (item['channel'], item['path'], item.get('version', ''))
                if counts.get(path, 0) >= 3 or any(duplicate(previous, item) for previous in shortlist):
                    continue
                shortlist.append(item)
                counts[path] = counts.get(path, 0) + 1
                if len(shortlist) >= settings.kb_rerank_candidates:
                    break
            diagnostic['candidates'] = len(shortlist)
            rank_query = scope.question if scope else query
            keys = [(rank_query,reranker.name,e.get('text','')) for e in shortlist]
            cache = scope.rerank_cache if scope else {}
            missing = list(dict.fromkeys(key for key in keys if key not in cache))
            diagnostic['computed'] = len(missing)
            if missing:
                ranked_scores = reranker.rerank(rank_query, [key[2] for key in missing])
                if len(ranked_scores) != len(missing) or not all(math.isfinite(float(s)) for s in ranked_scores):
                    raise ValueError('重排服务返回数量或分数无效')
                cache.update(zip(missing,ranked_scores))
            scores = [cache[key] for key in keys]
            if len(scores) == len(shortlist):
                for evidence, score in zip(shortlist, scores):
                    evidence['rank_score'] = float(score)
                shortlist.sort(key=lambda item: (int(item.get('relation_type') == 'exact_source'), item['rank_score']), reverse=True)
                result = [item for item in shortlist if item.get('relation_type') == 'exact_source' or item['rank_score'] >= settings.kb_rerank_min_score]
        except Exception as exc:
            diagnostic['error'] = type(exc).__name__
        finally:
            diagnostic['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            if scope:
                scope.diagnostics.append(diagnostic)
    # A file contributes at most three passages; preserve different files/versions separately.
    out, counts = [], {}
    for evidence in result:
        path = (evidence['channel'], evidence['path'], evidence.get('version', ''))
        if counts.get(path, 0) >= 3 or any(duplicate(previous, evidence) for previous in out):
            continue
        counts[path] = counts.get(path, 0) + 1; evidence.pop('_order', None); out.append(evidence)
    return out[:limit]
