"""Nightly graph analytics: FalkorDB algorithms whose scores become triage features.

PageRank and betweenness on the TRANSFER network show collectors and brokers; label
propagation groups accounts that trade with each other; WCC over shared identifiers finds
people who are probably operated by the same hands.
"""
from __future__ import annotations

import time

from . import db

ALGORITHMS = {
    "pagerank": """CALL algo.pageRank('Account', 'TRANSFER') YIELD node, score
                   SET node.pagerank = score""",
    "betweenness": """CALL algo.betweenness({nodeLabels: ['Account'], relationshipTypes: ['TRANSFER'],
                                             samplingSize: 256, samplingSeed: 42}) YIELD node, score
                      SET node.betweenness = score""",
    "community": """CALL algo.labelPropagation({nodeLabels: ['Account'], relationshipTypes: ['TRANSFER']})
                    YIELD node, communityId SET node.community = communityId""",
    "identity_wcc": """CALL algo.WCC({nodeLabels: ['Person', 'Company', 'Device', 'IP', 'Phone'],
                                      relationshipTypes: ['USES', 'LOGGED_IN_FROM', 'HAS_PHONE']})
                       YIELD node, componentId SET node.identity_cluster = componentId""",
}


def run_analytics(tenant: str) -> dict:
    g = db.graph(tenant)
    timings = {}
    for name, cypher in ALGORITHMS.items():
        started = time.perf_counter()
        g.query(cypher)
        timings[name] = round((time.perf_counter() - started) * 1000, 1)
    # Identity cluster size per party, so triage can read it without re-running WCC.
    g.query("""MATCH (p:Party) WHERE p.identity_cluster IS NOT NULL
               WITH p.identity_cluster AS c, collect(p) AS ps
               UNWIND ps AS p SET p.identity_cluster_size = size(ps)""")
    return {"tenant": tenant, "ms": timings}
