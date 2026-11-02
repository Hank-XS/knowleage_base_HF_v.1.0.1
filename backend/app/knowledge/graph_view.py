"""Scoped graph projection. Stored parser entities and source ranges stay intact."""
from collections import Counter

from .. import db as database
from .browsing import relative_source
from .catalog import classified_graph_nodes, current_project_jobs


def file_node_ids(doc, nodes):
    if doc.asset_type == 'code' and doc.project_job:
        path = relative_source(doc)
        return {n['id'] for n in nodes if n['props'].get('project_job') == doc.project_job
                and n['props'].get('path', '').replace('\\', '/') == path}
    return {n['id'] for n in nodes if n['props'].get('doc_id') == doc.id}


def project_node(node):
    label = node['label']
    if label == 'CodeUnit':
        label = 'Procedure' if node['props'].get('kind') == 'function' else 'Program'
    return {**node, 'label': label}


def build_graph(store, *, library='', project='', version='', tag='', history=False,
                detail=False, doc_id='', neighbors=True, view='structure', cross_system=False):
    from .associations import enrich, file_graph
    dump = store.dump()
    nodes, edges = enrich(classified_graph_nodes(dump['nodes']), dump['edges'])
    if not cross_system:
        edges = [e for e in edges if not e.get('props', {}).get('cross_system')]
    current = current_project_jobs()
    if view == 'files':
        nodes, edges = file_graph(nodes, edges)
    anchor = None
    pinned = ''
    if doc_id:
        with database.SessionLocal() as db:
            doc = db.get(database.KbDocument, doc_id)
            if not doc:
                raise ValueError('文件不存在')
            library, project, pinned = doc.library_key, doc.project, doc.project_job
            anchor = file_node_ids(doc, nodes)
    def eligible(n):
        job = n['props'].get('project_job')
        return not job or job in current or job == pinned or history or bool(version and not doc_id)
    available = [n for n in nodes if eligible(n)]
    def matches(n):
        p = n['props']
        return ((not library or p.get('library') == library or p.get('library', '').startswith(library + '/'))
                and (not project or p.get('project') == project)
                and (not version or p.get('version') == version)
                and (not tag or tag in p.get('tags', [])))
    owned = anchor if anchor is not None else {n['id'] for n in available if matches(n)}
    selected = set(owned)
    if neighbors and (doc_id or project or (cross_system and library)):
        allowed = {n['id'] for n in available if cross_system or not library or n['props'].get('library') == library}
        for edge in edges:
            if edge['src'] in owned or edge['dst'] in owned:
                selected.update({edge['src'], edge['dst']} & allowed)
    scoped = [n for n in available if n['id'] in selected and (view == 'files' or detail or
              (n['label'] not in {'Field', 'DocumentSection'} and n['props'].get('kind') != 'function'))]
    scoped = [project_node(n) for n in scoped]
    scoped.sort(key=lambda n: (n['label'] in {'Field', 'DocumentSection'}, n['id'] not in owned, n['label']))
    ids = {n['id'] for n in scoped}
    edges = [e for e in edges if e['src'] in ids and e['dst'] in ids]
    visible = scoped[:500]
    visible_ids = {n['id'] for n in visible}
    visible_edges = [e for e in edges if e['src'] in visible_ids and e['dst'] in visible_ids]
    return dict(nodes=[dict(id=n['id'], label=n['label'], name=n['props'].get('name', n['id']),
                            props=n['props'], external=n['id'] not in owned) for n in visible],
                edges=visible_edges[:1500], stats=dict(nodes=len(scoped), edges=len(edges),
                cross_project=sum(bool(e.get('props', {}).get('cross_project')) for e in edges),
                by_label=dict(Counter(n['label'] for n in scoped))),
                truncated=len(scoped) > 500 or len(visible_edges) > 1500,
                scope=dict(doc_id=doc_id, library=library, project=project, version=version, view=view))
