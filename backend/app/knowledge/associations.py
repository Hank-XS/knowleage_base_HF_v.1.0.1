"""Evidence-based links between independently uploaded, current code projects."""
from collections import defaultdict
from functools import lru_cache
from pathlib import PurePosixPath
import json
import re

from sqlalchemy import select
from .. import db as database
from .catalog import current_project_jobs


@lru_cache(maxsize=128)
def _legacy_references(job_id, root):
    from pathlib import Path
    file = Path(root) / 'result.json'
    if not file.is_file():
        return []
    result = json.loads(file.read_text('utf-8'))
    return [r for r in result.get('unresolved', []) if r['kind'] in {'calls', 'imports'}] + [
        dict(name=n['props']['name'], kind='imports', path=n['props']['path'], line=n['props']['start_line'])
        for n in result.get('nodes', []) if n['props'].get('kind') == 'import']


def enrich(store_nodes, store_edges):
    """Derived links are rebuilt from current snapshots; no source or parser slices change."""
    from ..ingest import code_project
    current = current_project_jobs()
    nodes = [n for n in store_nodes if n['props'].get('project_job') in current]
    by_file = defaultdict(list)
    programs, copies = defaultdict(list), defaultdict(list)
    for node in nodes:
        p = node['props']; by_file[(p['project_job'], p.get('path'))].append(node)
        if p.get('kind') == 'module':
            programs[p.get('name', '').upper()].append(node)
        if node['label'] == 'CodeFile' and PurePosixPath(p.get('path', '')).suffix.lower() == '.cpy':
            copies[PurePosixPath(p['path']).stem.upper()].append(node)
    with database.SessionLocal() as db:
        jobs = db.scalars(select(database.IngestJob).where(database.IngestJob.id.in_(current))).all() if current else []
        docs = db.scalars(select(database.KbDocument).where(database.KbDocument.project_job.in_(current))).all() if current else []
        doc_map = {(d.project_job, d.source_path.split('/source/', 1)[-1]): d for d in docs}
        contents = {}
        derived, seen = [], set()
        for job in jobs:
            refs = job.options_json.get('external_references')
            if refs is None or job.options_json.get('reference_schema') != 2:
                refs = _legacy_references(job.id, str(code_project.snapshot_root(job.id)))
            for ref in refs:
                if ref['kind'] not in {'calls', 'imports'}:
                    continue
                index = programs if ref['kind'] == 'calls' else copies
                name = PurePosixPath(ref['name'].strip('"\'')).stem.upper()
                same_job = [n for n in index.get(name, []) if n['props']['project_job'] == job.id]
                if ref['kind'] == 'imports' and not same_job and any(d.project_job == job.id and d.doc_type.lower() == 'cpy' and PurePosixPath(d.source_path).stem.upper() == name for d in docs):
                    continue  # A deliberately cleaned local definition must not be rebound elsewhere.
                candidates = same_job if ref['kind'] == 'imports' and same_job else [n for n in index.get(name, []) if n['props']['project_job'] != job.id]
                local = [n for n in candidates if n['props'].get('library') == job.options_json.get('library')]
                candidates = local or candidates
                if len(candidates) != 1:
                    continue
                target = candidates[0]
                file_key = (job.id, ref['path'])
                source_nodes = by_file.get(file_key, [])
                source = next((n for n in source_nodes if n['props'].get('kind') == 'module'), None)
                source = source or next((n for n in source_nodes if n['label'] == 'CodeFile'), None)
                doc = doc_map.get(file_key)
                if not source or not doc:
                    continue
                if doc.id not in contents:
                    contents[doc.id] = db.scalar(select(database.KbDocVersion.content).where(
                        database.KbDocVersion.doc_id == doc.id, database.KbDocVersion.version == doc.version)) or ''
                lines = contents[doc.id].splitlines()
                line = max(1, ref.get('line') or 1)
                snippet = '\n'.join(s for s in lines[max(0, line - 2):line + 2] if len(s) < 7 or s[6] != '*')
                literal = (r'\bCALL\s+[\"\']' + re.escape(name) + r'[\"\']') if ref['kind'] == 'calls' else (r'\bCOPY\s+[\"\']?' + re.escape(name) + r'(?![\w-])')
                if not re.search(literal, snippet, re.I):
                    continue
                relation = 'CALLS' if ref['kind'] == 'calls' else 'IMPORTS'
                key = source['id'], relation, target['id'], line
                if key in seen:
                    continue
                seen.add(key)
                derived.append(dict(src=source['id'], dst=target['id'], rel=relation,
                    props=dict(cross_project=job.id != target['props']['project_job'], cross_system=source['props'].get('library') != target['props'].get('library'),
                               source_job=job.id, target_job=target['props']['project_job'], line=line,
                               symbol=name, evidence=snippet.strip()[:600], method='literal_unique_symbol',
                               reason='静态引用与当前有效工程中的唯一同名定义匹配')))
    doc_ids = {(d.project_job, d.source_path.split('/source/', 1)[-1]): d.id for d in docs}
    enriched = [{**n, 'props': {**n['props'], **({'doc_id': doc_ids[(n['props'].get('project_job'), n['props'].get('path'))]} if
                 (n['props'].get('project_job'), n['props'].get('path')) in doc_ids else {})}} for n in store_nodes]
    return enriched, [*store_edges, *derived]


def file_graph(nodes, edges):
    files = [n for n in nodes if n['label'] in {'CodeFile', 'Document'}]
    index = {(n['props'].get('project_job'), n['props'].get('path')): n['id'] for n in files if n['label'] == 'CodeFile'}
    owners = {n['id']: n['id'] if n['label'] in {'CodeFile', 'Document', 'System'} else
              index.get((n['props'].get('project_job'), n['props'].get('path'))) or ('document/' + n['props']['doc_id'] if n['props'].get('doc_id') else '') for n in nodes}
    result = {}
    for edge in edges:
        source, target = owners.get(edge['src']), owners.get(edge['dst'])
        if source and target and source != target:
            key = source, target, edge['rel']
            props = edge.get('props', {})
            if key not in result:
                result[key] = dict(src=source, dst=target, rel=edge['rel'],
                                   props={**props, 'occurrences': 0, 'evidence_items': []})
            group = result[key]['props']
            group['occurrences'] += 1
            group['cross_project'] = group.get('cross_project', False) or props.get('cross_project', False)
            if len(group['evidence_items']) < 20:
                group['evidence_items'].append(props)
    return files, list(result.values())
