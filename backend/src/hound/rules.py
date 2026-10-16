"""Baseline transaction monitoring: the simple threshold rules banks already run.

These rules are intentionally naive, as production rule engines are. They generate the alert
queue Hound has to work through; most alerts are false positives that need context to clear.
"""
from __future__ import annotations

import json

from . import db, memory
from .world.generator import T0

WEEK = 7 * 86_400
H48 = 2 * 86_400

RULES: dict[str, dict] = {
    "R1": {
        "name": "Cash deposits just below CTR threshold",
        "typology": "STRUCTURING", "severity": 0.6,
        "cypher": """
MATCH (:Branch)-[c1:CASH_DEPOSIT]->(a:Account)<-[c2:CASH_DEPOSIT]-(:Branch)
WHERE c1.amount >= 8000 AND c1.amount < 10000 AND c2.amount >= 8000 AND c2.amount < 10000
  AND c1.id < c2.id AND abs(c2.ts - c1.ts) <= $week
WITH a, count(*) AS pairs, collect(DISTINCT c1.amount) + collect(DISTINCT c2.amount) AS amts
RETURN a.id AS account, pairs, size(amts) AS deposits, reduce(s = 0.0, x IN amts | s + x) AS total""",
        "describe": lambda r: f"{r['deposits']} cash deposits between $8,000 and $9,999 within 7-day windows "
                              f"(${r['total']:,.0f} total)",
    },
    "R2": {
        "name": "Fan-out to many counterparties",
        "typology": "FAN_OUT", "severity": 0.4,
        "cypher": """
MATCH (a:Account)-[t:TRANSFER]->(b:Account)
WHERE NOT a:External AND t.channel IN ['ach', 'wire', 'p2p']
WITH a, toInteger((t.ts - $t0) / $week) AS wk, count(DISTINCT b) AS cps, sum(t.amount) AS total
WHERE cps >= 15
RETURN a.id AS account, max(cps) AS peak_counterparties, sum(total) AS total, count(wk) AS weeks""",
        "describe": lambda r: f"Up to {r['peak_counterparties']} distinct payees in a week across {r['weeks']} weeks "
                              f"(${r['total']:,.0f})",
    },
    "R3": {
        "name": "Fan-in from many senders",
        "typology": "FAN_IN", "severity": 0.45,
        "cypher": """
MATCH (s:Account)-[t:TRANSFER]->(a:Account)
WHERE NOT a:External AND t.channel IN ['ach', 'wire', 'p2p']
WITH a, toInteger((t.ts - $t0) / $week) AS wk, count(DISTINCT s) AS senders, sum(t.amount) AS total
WHERE senders >= 7
RETURN a.id AS account, max(senders) AS peak_senders, sum(total) AS total, count(wk) AS weeks""",
        "describe": lambda r: f"Up to {r['peak_senders']} distinct senders in a week (${r['total']:,.0f})",
    },
    "R4": {
        "name": "Rapid movement of funds (pass-through)",
        "typology": "RAPID_MOVEMENT", "severity": 0.55,
        "cypher": """
MATCH (:Account)-[i:TRANSFER]->(a:Account)
WHERE NOT a:External AND i.amount >= 500
OPTIONAL MATCH (a)-[o:TRANSFER]->(:Account)
WHERE o.ts >= i.ts AND o.ts <= i.ts + $h48 AND o.channel <> 'card'
WITH a, i, sum(o.amount) AS out48
WITH a, sum(i.amount) AS inflow, count(i) AS n,
     sum(CASE WHEN out48 > i.amount THEN i.amount ELSE out48 END) AS moved
WHERE inflow >= 5000 AND moved / inflow >= 0.8 AND (n >= 2 OR inflow >= 50000)
RETURN a.id AS account, inflow, moved, n AS inbound_count, moved / inflow AS ratio""",
        "describe": lambda r: f"{r['ratio']:.0%} of ${r['inflow']:,.0f} inbound left within 48 hours "
                              f"({r['inbound_count']} credits)",
    },
    "R5": {
        "name": "Large wire with high-risk jurisdiction",
        "typology": "HIGH_RISK_GEO", "severity": 0.5,
        "cypher": """
MATCH (a:Account)-[t:TRANSFER]-(x:Account)-[:IN_JURISDICTION]->(j:Jurisdiction {risk: 'high'})
WHERE NOT a:External AND x:External AND t.amount >= 25000
RETURN a.id AS account, count(t) AS wires, sum(t.amount) AS total, collect(DISTINCT j.code) AS jurisdictions""",
        "describe": lambda r: f"{r['wires']} wire(s) totalling ${r['total']:,.0f} with {', '.join(r['jurisdictions'])}",
    },
    "R6": {
        "name": "High inbound value on a new account",
        "typology": "NEW_ACCOUNT", "severity": 0.45,
        "cypher": """
MATCH (:Account)-[t:TRANSFER]->(a:Account)
WHERE NOT a:External AND t.ts - a.opened <= 60 * 86400 AND $end - a.opened <= 90 * 86400
WITH a, sum(t.amount) AS inbound, count(t) AS n
WHERE inbound >= 30000
RETURN a.id AS account, inbound, n AS credits, ($end - a.opened) / 86400 AS age_days""",
        "describe": lambda r: f"${r['inbound']:,.0f} received in the first 60 days of a {r['age_days']}-day-old account",
    },
}


def run_rules(tenant: str) -> dict:
    from .world.generator import SIM_END
    g = db.graph(tenant)
    g.query("MATCH (al:Alert) DETACH DELETE al")
    params = {"week": WEEK, "t0": T0, "h48": H48, "end": SIM_END}
    alerts = []
    for code, rule in RULES.items():
        found, _ = db.rows(g, rule["cypher"], params)
        for r in found:
            alerts.append({
                "id": f"ALR-{code}-{r['account'].split('-')[1]}",
                "rule": code, "rule_name": rule["name"], "typology": rule["typology"],
                "severity": rule["severity"], "account": r["account"],
                "description": rule["describe"](r), "details": json.dumps(r, default=str),
                "created": SIM_END - 3600 * (len(alerts) % 20), "status": "NEW",
            })
    db.batched(g, """UNWIND $rows AS r MATCH (a:Account {id: r.account})
                     CREATE (al:Alert {id: r.id, rule: r.rule, rule_name: r.rule_name, typology: r.typology,
                                       severity: r.severity, description: r.description, details: r.details,
                                       created: r.created, status: r.status})-[:ON]->(a)""", alerts)
    by_rule: dict[str, int] = {}
    for a in alerts:
        by_rule[a["rule"]] = by_rule.get(a["rule"], 0) + 1
    return {"tenant": tenant, "alerts": len(alerts), "by_rule": by_rule}


def rule_cypher() -> dict[str, str]:
    return {code: r["cypher"].strip() for code, r in RULES.items()}

