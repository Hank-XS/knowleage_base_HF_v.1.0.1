"""知识图谱存储：MemGraphStore（内嵌，JSON 持久化） + Neo4jGraphStore（可选）。

节点/关系模型对应设计文档 4.2 节（业务层/数据层/执行层）。
两实现共享同一接口：upsert_node / upsert_edge / find / neighbors / impact_subgraph / alias_closure。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, settings

IMPACT_RELS = {"CALLS", "READS", "WRITES", "REALIZED_BY", "IMPLEMENTED_BY", "USES", "RAISED_IN", "HAS_FIELD", "MAPPED_FROM", "PART_OF"}


class MemGraphStore:
    """进程内属性图；运行结果保存到被 Git 忽略的 data/runtime。"""

    def __init__(self) -> None:
        self._path = DATA_DIR / "runtime" / "graph_store.json"
        self._lock = threading.RLock()
        self._nodes: dict[str, dict] = {}
        self._edges: list[dict] = []
        self._load()

    # ------------------------------------------------------------ persist
    def _load(self) -> None:
        source = self._path if self._path.exists() else DATA_DIR / "graph_store.json"
        if source.exists():
            raw = json.loads(source.read_text("utf-8"))
            self._nodes = {n["id"]: n for n in raw["nodes"]}
            self._edges = raw["edges"]

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"nodes": list(self._nodes.values()), "edges": self._edges},
                           ensure_ascii=False), "utf-8")

    # ------------------------------------------------------------ write
    def upsert_node(self, node_id: str, label: str, props: dict | None = None) -> str:
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                node = {"id": node_id, "label": label, "props": {}}
                self._nodes[node_id] = node
            node["label"] = label or node["label"]
            node["props"].update(props or {})
            return node_id

    def upsert_edge(self, src: str, rel: str, dst: str, props: dict | None = None) -> None:
        with self._lock:
            for e in self._edges:
                if e["src"] == src and e["rel"] == rel and e["dst"] == dst:
                    e["props"].update(props or {})
                    return
            self._edges.append({"src": src, "rel": rel, "dst": dst, "props": props or {}})

    def remove_edges(self, src: str, rel: str | None = None, dst: str | None = None) -> None:
        with self._lock:
            self._edges = [e for e in self._edges
                           if not (e["src"] == src and (rel is None or e["rel"] == rel)
                                   and (dst is None or e["dst"] == dst))]

    def delete_by_meta(self, key: str, value: str) -> None:
        """Remove one ingestion snapshot, including incident edges."""
        with self._lock:
            ids = {nid for nid, n in self._nodes.items() if n['props'].get(key) == value}
            self._nodes = {nid: n for nid, n in self._nodes.items() if nid not in ids}
            self._edges = [e for e in self._edges if e['src'] not in ids and e['dst'] not in ids]

    # ------------------------------------------------------------ read
    def node(self, node_id: str) -> dict | None:
        return self._nodes.get(node_id)

    def find(self, label: str | None = None, **props) -> list[dict]:
        with self._lock:
            out = []
            for n in self._nodes.values():
                if label and n["label"] != label:
                    continue
                if all(n["props"].get(k) == v for k, v in props.items()):
                    out.append(n)
            return out

    def find_by_name(self, name: str) -> list[dict]:
        with self._lock:
            name_l = str(name).strip().lower()
            return [n for n in self._nodes.values()
                    if n["props"].get("name", "").lower() == name_l
                    or n["id"].lower().endswith("/" + name_l)
                    or n["id"].lower() == name_l]

    def edges_of(self, node_id: str, rels: set[str] | None = None) -> list[dict]:
        with self._lock:
            return [e for e in self._edges
                    if (e["src"] == node_id or e["dst"] == node_id)
                    and (rels is None or e["rel"] in rels)]

    def neighbors(self, node_id: str, max_hops: int = 1,
                  rels: set[str] | None = None) -> tuple[list[dict], list[dict]]:
        """BFS 返回（节点, 边）子图。"""
        with self._lock:
            adj: dict[str, list[dict]] = {}
            for e in self._edges:
                if rels and e["rel"] not in rels:
                    continue
                adj.setdefault(e["src"], []).append(e)
                adj.setdefault(e["dst"], []).append(e)
            seen_n, seen_e, frontier = {node_id}, [], [node_id]
            for _ in range(max_hops):
                nxt = []
                for cur in frontier:
                    for e in adj.get(cur, []):
                        if e not in seen_e:
                            seen_e.append(e)
                        other = e["dst"] if e["src"] == cur else e["src"]
                        if other not in seen_n:
                            seen_n.add(other)
                            nxt.append(other)
                frontier = nxt
            nodes = [self._nodes[n] for n in seen_n if n in self._nodes]
            return nodes, seen_e

    def impact(self, target: str, depth: int = 3) -> dict:
        """影响面：沿 IMPACT_RELS 外扩，返回分层统计与证据路径。"""
        nodes, edges = self.neighbors(target, max_hops=depth, rels=IMPACT_RELS)
        root = self._nodes.get(target)
        by_label: dict[str, int] = {}
        for n in nodes:
            if n["id"] != target:
                by_label[n["label"]] = by_label.get(n["label"], 0) + 1
        paths = [
            f"{self._nodes[e['src']]['props'].get('name', e['src'])} -[{e['rel']}]-> "
            f"{self._nodes[e['dst']]['props'].get('name', e['dst'])}"
            for e in edges[:30] if e["src"] in self._nodes and e["dst"] in self._nodes
        ]
        affected = len(nodes) - 1
        coupling = round(min(1.0, affected / 25.0), 2)
        return {"target": target, "root": root, "affected": affected, "by_label": by_label,
                "coupling_score": coupling, "paths": paths, "depth": depth}

    def alias_closure(self, node_id: str) -> list[dict]:
        _, edges = self.neighbors(node_id, max_hops=2, rels={"ALIAS_OF"})
        ids = {e["src"] for e in edges} | {e["dst"] for e in edges} | {node_id}
        return [self._nodes[i] for i in ids if i in self._nodes]

    def three_layer(self, fp_name: str) -> dict:
        """业务层→执行层→数据层一次查全（设计 5.4 / 附录A 模板1）。"""
        fps = self.find_by_name(fp_name)
        nodes, edges = [], []
        for fp in fps:
            ns, es = self.neighbors(fp["id"], max_hops=4,
                                    rels={"REALIZED_BY", "USES", "HAS_FIELD", "MAPPED_FROM",
                                          "IMPLEMENTED_BY", "RAISED_IN", "PART_OF"})
            nodes.extend(ns)
            edges.extend(es)
        uniq_n = {n["id"]: n for n in nodes}
        return {"nodes": list(uniq_n.values()), "edges": edges}

    def stats(self) -> dict:
        by_label: dict[str, int] = {}
        for n in self._nodes.values():
            by_label[n["label"]] = by_label.get(n["label"], 0) + 1
        return {"nodes": len(self._nodes), "edges": len(self._edges), "by_label": by_label}

    def dump(self) -> dict:
        with self._lock:
            return {"nodes": list(self._nodes.values()), "edges": self._edges}

    def clear(self) -> None:
        with self._lock:
            self._nodes, self._edges = {}, []
            self.save()


class Neo4jGraphStore(MemGraphStore):
    """Neo4j 实现：写穿透到 Cypher，读用内嵌镜像（演示期简化，保证接口一致）。"""

    def __init__(self) -> None:
        super().__init__()
        from neo4j import GraphDatabase  # optional dependency
        self._drv = GraphDatabase.driver(
            settings.kb_graph_url, auth=(settings.kb_graph_user, settings.kb_graph_password))

    def upsert_node(self, node_id: str, label: str, props: dict | None = None) -> str:
        nid = super().upsert_node(node_id, label, props)
        safe = (props or {}) | {"kb_id": node_id}
        with self._drv.session() as s:
            s.run(f"MERGE (n:{label} {{kb_id: $id}}) SET n += $p", id=node_id, p=safe)
        return nid

    def delete_by_meta(self, key: str, value: str) -> None:
        with self._drv.session() as s:
            s.run('MATCH (n) WHERE n[$key] = $value DETACH DELETE n', key=key, value=value)
        super().delete_by_meta(key, value)

    def upsert_edge(self, src: str, rel: str, dst: str, props: dict | None = None) -> None:
        super().upsert_edge(src, rel, dst, props)
        with self._drv.session() as s:
            s.run(
                f"MATCH (a {{kb_id: $s}}), (b {{kb_id: $d}}) "
                f"MERGE (a)-[r:{rel}]->(b) SET r += $p", s=src, d=dst, p=props or {})


def build_graph_store() -> MemGraphStore:
    if settings.kb_graph_url:
        try:
            return Neo4jGraphStore()
        except Exception:  # pragma: no cover - 驱动未装或连接失败则回退
            return MemGraphStore()
    return MemGraphStore()


graph_store = build_graph_store()
