"""One current, indexed association snapshot for visualization and RAG. Never modifies originals."""
from collections import defaultdict
from threading import RLock
from weakref import WeakKeyDictionary

from .catalog import current_project_jobs, classified_graph_nodes

_cache = WeakKeyDictionary()
_lock = RLock()


class RelationGraph:
    def __init__(self, nodes, edges):
        self.nodes = {n['id']: n for n in nodes}
        self._nodes = self.nodes
        self.edges = edges
        self.names, self.adjacency = defaultdict(list), defaultdict(list)
        for node in nodes:
            self.names[str(node['props'].get('name', '')).casefold()].append(node)
        for edge in edges:
            self.adjacency[edge['src']].append(edge)
            self.adjacency[edge['dst']].append(edge)

    def dump(self):
        return dict(nodes=list(self.nodes.values()), edges=self.edges)

    def node(self, key):
        return self.nodes.get(key.removeprefix('graph://'))

    def find_by_name(self, name):
        return self.names.get(str(name).strip().casefold(), []) or ([self.nodes[name]] if name in self.nodes else [])

    def neighbors(self, node_id, max_hops=1, rels=None):
        ids, selected, seen = {node_id}, [], set()
        frontier = {node_id}
        for _ in range(max_hops):
            following = set()
            for key in frontier:
                for edge in self.adjacency.get(key, []):
                    if rels and edge['rel'] not in rels:
                        continue
                    identity = (edge['src'], edge['rel'], edge['dst'], edge.get('props', {}).get('line'))
                    if identity not in seen:
                        seen.add(identity); selected.append(edge)
                    following.update({edge['src'], edge['dst']} - ids)
            ids.update(following); frontier = following
        return [self.nodes[key] for key in ids if key in self.nodes], selected

    def impact(self, target, depth=3):
        from ..stores.graph import MemGraphStore
        return MemGraphStore.impact(self, target, depth)


def relation_graph(store):
    from .associations import enrich
    current = frozenset(current_project_jobs())
    token = (store.revision, current)
    with _lock:
        cached = _cache.get(store)
        if cached and cached[0] == token:
            return cached[1]
        dump = store.dump()
        nodes, edges = enrich(classified_graph_nodes(dump['nodes']), dump['edges'])
        # Retain historical snapshots for explicit version views; association matching is current-only.
        graph = RelationGraph(nodes, edges)
        graph.generation = str(token[0]) + ':' + ','.join(sorted(current))
        _cache[store] = (token, graph)
        return graph
