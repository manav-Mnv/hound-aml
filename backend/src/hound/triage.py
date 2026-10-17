"""Triage agent: score every open alert from graph context and group related alerts.

Runs in well under a second for the whole queue, so the expensive investigator agent only
spends tokens where the graph says it matters. Every point of the score has a reason string.
"""
from __future__ import annotations

import json

from . import consortium, db
from .world.generator import SIM_END

FEATURES_CYPHER = """
MATCH (al:Alert)-[:ON]->(a:Account)<-[:HOLDS]-(p:Party)
WHERE al.status IN ['NEW', 'TRIAGED']
OPTIONAL MATCH (other:Alert)-[:ON]->(a) WHERE other.id <> al.id
WITH al, a, p, count(DISTINCT other) AS same_account_alerts
OPTIONAL MATCH (p)-[:USES|LOGGED_IN_FROM|HAS_PHONE]->(i)<-[:USES|LOGGED_IN_FROM|HAS_PHONE]-(q:Party)
WITH al, a, p, same_account_alerts, collect(DISTINCT q) AS linked
WITH al, a, p, same_account_alerts, linked,
     size([x IN linked WHERE x.onboarded > $recent]) AS linked_new,
     reduce(s = 0, x IN linked | s + size([(x)-[:HOLDS]->(:Account)<-[:ON]-(:Alert) | 1])) AS linked_alerts
OPTIONAL MATCH (a)-[t:TRANSFER]-(x:External)-[:IN_JURISDICTION]->(:Jurisdiction {risk: 'high'})
WITH al, a, p, same_account_alerts, linked, linked_new, linked_alerts, sum(t.amount) AS high_risk_value
OPTIONAL MATCH (a)-[:TRANSFER]-(:Account)<-[:HOLDS]-(cp:Party)<-[:OWNS*1..3]-(s:Sanctioned)
WITH al, a, p, same_account_alerts, linked, linked_new, linked_alerts, high_risk_value, count(DISTINCT s) AS sanctioned_owners
OPTIONAL MATCH (c:Case)-[:SUBJECT]->(p) WHERE c.disposition = 'FALSE_POSITIVE'
OPTIONAL MATCH (l:Lesson)-[:ABOUT]->(p)
RETURN al.id AS alert, al.rule AS rule, al.typology AS typology, al.severity AS severity, al.details AS details,
       a.id AS account, a.opened AS opened, a.pagerank AS pagerank, a.community AS community,
       p.id AS party, p.name AS name, p.onboarded AS onboarded, p.identity_cluster AS identity_cluster,
       same_account_alerts, size(linked) AS linked_parties, linked_new, linked_alerts, high_risk_value,
       sanctioned_owners, count(DISTINCT c) AS prior_fp_cases, count(DISTINCT l) AS lessons
"""


def _ident_items(g, party_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    rows, _ = db.rows(g, """UNWIND $ids AS pid MATCH (p:Party {id: pid})-[:USES|HAS_PHONE|LOGGED_IN_FROM]->(i)
                            RETURN pid, labels(i)[0] AS label, coalesce(i.fingerprint, i.number, i.addr) AS value""",
                      {"ids": party_ids})
    kinds = {"Device": "device", "Phone": "phone", "IP": "ip"}
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        if r["value"]:
            out.setdefault(r["pid"], []).append((kinds[r["label"]], r["value"]))
    return out


def score_alerts(tenant: str) -> list[dict]:
    g = db.graph(tenant)
    rows, ms = db.rows(g, FEATURES_CYPHER, {"recent": SIM_END - 90 * 86400}, timeout_ms=180_000)
    pr_sorted = sorted(r["pagerank"] or 0 for r in rows)
    idents = _ident_items(g, list({r["party"] for r in rows}))
    scored = []
    for r in rows:
        reasons: list[tuple[float, str]] = [(r["severity"] * 30, f"rule {r['rule']} base severity")]
        age_days = (SIM_END - r["opened"]) // 86400 if r["opened"] else None
        tenure = (SIM_END - r["onboarded"]) // 86400 if r["onboarded"] else None
        if age_days is not None and age_days <= 90:
            reasons.append((10, f"account opened {age_days} days ago"))
        if r["linked_parties"] >= 2:
            reasons.append((min(25, 4 * r["linked_parties"]), f"shares device/IP/phone with {r['linked_parties']} other parties"))
        if r["linked_new"] >= 2:
            reasons.append((10, f"{r['linked_new']} of those linked parties onboarded in the last 90 days"))
        if r["linked_alerts"] >= 2:
            reasons.append((10, f"{r['linked_alerts']} alerts on linked parties"))
        if r["same_account_alerts"]:
            reasons.append((5 * min(r["same_account_alerts"], 3), f"{r['same_account_alerts']} other rule(s) fired on the same account"))
        if (r["high_risk_value"] or 0) >= 25000:
            reasons.append((8, f"${r['high_risk_value']:,.0f} exchanged with high-risk jurisdictions"))
        if r["sanctioned_owners"]:
            reasons.append((35, f"counterparty owned by {r['sanctioned_owners']} designated part(ies) within 3 hops"))
        hits = consortium.lookup(tenant, idents.get(r["party"], []))
        if hits:
            reasons.append((30, f"{len(hits)} identifier(s) reported by {hits[0]['institution']} for {hits[0]['typology']}"))
        if r["prior_fp_cases"]:
            reasons.append((-25, f"{r['prior_fp_cases']} prior case(s) on this customer closed as false positive"))
        if r["lessons"]:
            reasons.append((-5, "analyst lesson on file for this customer"))
        if tenure is not None and tenure > 1500 and not r["linked_parties"]:
            reasons.append((-8, f"established customer ({tenure // 365} years), no shared identifiers"))
        if r["pagerank"] and pr_sorted and r["pagerank"] >= pr_sorted[int(len(pr_sorted) * 0.97)]:
            reasons.append((6, "top 3% PageRank in the transfer network (collector-like)"))
        score = max(0.0, min(100.0, sum(w for w, _ in reasons)))
        scored.append({**{k: r[k] for k in ("alert", "rule", "typology", "account", "party", "name", "identity_cluster")},
                       "score": round(score, 1), "reasons": [f"{'+' if w >= 0 else ''}{w:.0f} {txt}" for w, txt in reasons],
                       "consortium_hits": len(hits)})
    links, _ = db.rows(g, """MATCH (:Alert)-[:ON]->(a1:Account)-[t:TRANSFER]-(a2:Account)<-[:ON]-(:Alert)
                             WHERE a1.id < a2.id AND t.amount >= 5000
                             RETURN DISTINCT a1.id AS a, a2.id AS b""")
    _group(scored, [(l["a"], l["b"]) for l in links])
    db.batched(g, """UNWIND $rows AS r MATCH (al:Alert {id: r.alert})
                     SET al.triage_score = r.score, al.triage_reasons = r.reasons, al.group = r.group,
                         al.status = CASE WHEN al.status = 'NEW' THEN 'TRIAGED' ELSE al.status END""", scored)
    return sorted(scored, key=lambda s: -s["score"])


def _group(scored: list[dict], money_links: list[tuple[str, str]]) -> None:
    """Union-find: alerts on the same account, the same identity cluster, or accounts that moved
    material money between each other belong in one case."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    cluster_members: dict = {}
    for s in scored:
        cluster_members.setdefault(s["identity_cluster"], set()).add(s["account"])
        find(s["account"])
    for cid, accounts in cluster_members.items():
        if cid is not None and len(accounts) >= 2:
            first, *rest = sorted(accounts)
            for other in rest:
                union(first, other)
    for a, b in money_links:
        union(a, b)
    roots: dict[str, list[str]] = {}
    for s in scored:
        roots.setdefault(find(s["account"]), []).append(s["account"])
    for s in scored:
        members = sorted(set(roots[find(s["account"])]))
        s["group"] = f"GRP-{members[0].split('-')[1]}" if len(members) > 1 else f"ACC-{s['account'].split('-')[1]}"


def queue(tenant: str) -> list[dict]:
    rows, _ = db.rows(db.graph(tenant), """
        MATCH (al:Alert)-[:ON]->(a:Account)<-[:HOLDS]-(p:Party)
        OPTIONAL MATCH (c:Case)-[:FROM_ALERT]->(al)
        RETURN al.id AS id, al.rule AS rule, al.rule_name AS rule_name, al.typology AS typology,
               al.description AS description, al.status AS status, al.triage_score AS score,
               al.triage_reasons AS reasons, al.group AS grp, a.id AS account, p.id AS party, p.name AS holder,
               labels(p) AS labels, c.id AS case_id, c.disposition AS disposition
        ORDER BY score DESC""")
    for r in rows:
        r["party_type"] = "Company" if "Company" in r.pop("labels") else "Person"
    return rows


def details(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
