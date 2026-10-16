"""FalkorDB access: one connection pool, many tenant graphs, JSON-safe results."""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from falkordb import Edge, FalkorDB, Graph, Node, Path

from .config import settings

TENANT_NAMES = {
    "alpha": "Alpha Bank (synthetic)",
    "beta": "Beta Credit Union (synthetic)",
}


@lru_cache(maxsize=1)
def client() -> FalkorDB:
    return FalkorDB(
        host=settings.falkor_host,
        port=settings.falkor_port,
        username=settings.falkor_username,
        password=settings.falkor_password,
    )


def graph(tenant: str) -> Graph:
    if tenant not in settings.tenants:
        raise ValueError(f"unknown tenant {tenant!r}")
    return client().select_graph(settings.graph_name(tenant))


def consortium() -> Graph:
    return client().select_graph(settings.consortium_graph)


def to_json(value: Any) -> Any:
    """Convert FalkorDB result values (nodes, edges, paths) into plain JSON."""
    if isinstance(value, Node):
        return {"_type": "node", "labels": list(value.labels or []), **_props(value.properties)}
    if isinstance(value, Edge):
        return {
            "_type": "edge",
            "rel": value.relation,
            "src": value.src_node,
            "dst": value.dest_node,
            **_props(value.properties),
        }
    if isinstance(value, Path):
        return {
            "_type": "path",
            "nodes": [to_json(n) for n in value.nodes()],
            "edges": [to_json(e) for e in value.edges()],
        }
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


def _props(props: dict) -> dict:
    return {k: to_json(v) for k, v in (props or {}).items()}


def rows(g: Graph, cypher: str, params: dict | None = None, *, write: bool = False,
         timeout_ms: int = 15000) -> tuple[list[dict], float]:
    """Run a query and return (rows as dicts, elapsed ms). Reads go through GRAPH.RO_QUERY."""
    started = time.perf_counter()
    if write:
        res = g.query(cypher, params or {}, timeout=timeout_ms)
    else:
        res = g.ro_query(cypher, params or {}, timeout=timeout_ms)
    elapsed = (time.perf_counter() - started) * 1000
    header = [h[1] if isinstance(h, (list, tuple)) else h for h in (res.header or [])]
    out = [dict(zip(header, (to_json(v) for v in row))) for row in res.result_set]
    return out, elapsed


def run(g: Graph, cypher: str, params: dict | None = None) -> None:
    g.query(cypher, params or {})


def batched(g: Graph, cypher: str, items: list[dict], size: int = 2000) -> None:
    """UNWIND-style bulk write: the query receives the batch as $rows."""
    for i in range(0, len(items), size):
        g.query(cypher, {"rows": items[i:i + size]})
