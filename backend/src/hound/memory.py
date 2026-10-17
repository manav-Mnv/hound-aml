"""Agent memory stored in the bank's graph, attached to the entities it is about.

Episodic   - (:Case), (:AgentRun), (:Finding), (:Evidence), (:SAR): what happened, who did it, why.
Semantic   - (:Lesson)-[:ABOUT]->(:Party|:Account): durable facts learned about an entity.
Procedural - (:Playbook)-[:STEP]->(:Step), refined by (:Lesson)-[:REFINES]->(:Playbook).

Because memory nodes hang off the same Party/Account nodes the transactions use, recalling
"have we seen anything like this before?" is a graph traversal, not a text search.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from . import db

PLAYBOOKS: dict[str, list[tuple[str, str]]] = {
    "STRUCTURING": [
        ("recall_memory", "Check prior cases and analyst lessons on the subject and linked parties."),
        ("cash_structuring_profile", "Profile cash deposits: share in the $8k-$10k band vs CTR-triggering deposits, branches used."),
        ("trace_money_flow", "Follow where the cash goes next (outbound, 3 hops, 7 days)."),
        ("shared_identifiers", "Check whether depositors share devices, IPs or addresses."),
        ("sanctions_exposure", "Check counterparties for sanctions or high-risk jurisdictions."),
    ],
    "MONEY_MULE": [
        ("recall_memory", "Check prior cases and lessons on the account and its identity cluster."),
        ("identity_cluster", "Run WCC over shared identifiers to find the ring."),
        ("pass_through_analysis", "Measure how fast and how much inbound money leaves."),
        ("trace_money_flow", "Follow outbound funds to the collector and cash-out point."),
        ("consortium_check", "Look up hashed identifiers in the consortium graph."),
    ],
    "ROUND_TRIPPING": [
        ("recall_memory", "Check prior cases on the subject and related companies."),
        ("find_cycles", "Search for closed loops of transfers that return to the subject."),
        ("corporate_network", "Check shared directors, owners and registered addresses."),
        ("network_position", "Check centrality and community of the subject."),
    ],
    "SANCTIONS_EVASION": [
        ("recall_memory", "Check prior cases on the subject and counterparties."),
        ("counterparty_summary", "List material counterparties and jurisdictions."),
        ("sanctions_exposure", "Compute aggregate blocked ownership (OFAC 50% rule) through ownership chains."),
        ("corporate_network", "Inspect ownership and directors of flagged counterparties."),
    ],
    "LAYERING": [
        ("recall_memory", "Check prior cases on the subject."),
        ("trace_money_flow", "Follow funds forward through time-ordered hops."),
        ("pass_through_analysis", "Measure retention and velocity at each hop."),
        ("counterparty_summary", "Check origin and destination jurisdictions."),
    ],
    "RAPID_MOVEMENT": [
        ("recall_memory", "Check prior cases and lessons on the account and linked parties."),
        ("pass_through_analysis", "Measure retention and velocity of inbound funds."),
        ("trace_money_flow", "Follow outbound funds through time-ordered hops."),
        ("identity_cluster", "Check whether the holder shares identifiers with other customers."),
        ("find_cycles", "Check whether funds return to the origin (round-tripping)."),
        ("consortium_check", "Look up hashed identifiers in the consortium graph."),
    ],
    "FAN_OUT": [
        ("recall_memory", "Check prior cases and lessons; payroll processors fan out by design."),
        ("counterparty_summary", "Summarise recipients and funding sources."),
        ("peer_comparison", "Compare activity with peers in the same industry."),
    ],
    "FAN_IN": [
        ("recall_memory", "Check prior cases and lessons on the recipient."),
        ("counterparty_summary", "Who are the senders, are they established customers?"),
        ("pass_through_analysis", "Does the money leave quickly?"),
        ("identity_cluster", "Do senders or the recipient share identifiers with others?"),
    ],
    "HIGH_RISK_GEO": [
        ("recall_memory", "Check prior cases and lessons."),
        ("counterparty_summary", "Is the foreign counterparty established and consistent with the business?"),
        ("sanctions_exposure", "Screen ownership of foreign counterparties."),
        ("peer_comparison", "Compare with expected activity and peers."),
    ],
    "NEW_ACCOUNT": [
        ("recall_memory", "Check prior cases on the customer and linked parties."),
        ("counterparty_summary", "Where did the large inflows come from?"),
        ("pass_through_analysis", "Did the funds move straight out?"),
        ("identity_cluster", "Does the new customer share identifiers with others?"),
    ],
}


def now() -> int:
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ----------------------------------------------------------------------------- playbooks

def ensure_playbooks(tenant: str, lessons: dict[str, str] | None = None) -> None:
    g = db.graph(tenant)
    for typology, steps in PLAYBOOKS.items():
        g.query("""MERGE (pb:Playbook {typology: $t}) ON CREATE SET pb.version = 1, pb.created = $now""",
                {"t": typology, "now": now()})
        g.query("""MATCH (pb:Playbook {typology: $t})-[s:STEP]->(st:Step) DELETE s, st""", {"t": typology})
        g.query("""MATCH (pb:Playbook {typology: $t})
                   UNWIND range(0, size($steps) - 1) AS i
                   CREATE (pb)-[:STEP {order: i}]->(:Step {tool: $steps[i][0], instruction: $steps[i][1]})""",
                {"t": typology, "steps": [list(s) for s in steps]})
    for typology, text in (lessons or {}).items():
        add_lesson(tenant, text, author="aml-ops", refines=typology)


def playbook(tenant: str, typology: str) -> dict:
    g = db.graph(tenant)
    steps, _ = db.rows(g, """MATCH (pb:Playbook {typology: $t})-[s:STEP]->(st:Step)
                             RETURN st.tool AS tool, st.instruction AS instruction, s.order AS ord ORDER BY ord""", {"t": typology})
    lessons, _ = db.rows(g, """MATCH (l:Lesson)-[:REFINES]->(:Playbook {typology: $t})
                               RETURN l.id AS id, l.text AS text, l.author AS author, l.created AS created
                               ORDER BY created""", {"t": typology})
    return {"typology": typology, "steps": steps, "lessons": lessons}


# ----------------------------------------------------------------------------- lessons

def add_lesson(tenant: str, text: str, *, author: str, about: list[str] | None = None,
               refines: str | None = None, case_id: str | None = None) -> str:
    g = db.graph(tenant)
    lid = new_id("LSN")
    g.query("CREATE (:Lesson {id: $id, text: $text, author: $author, created: $now})",
            {"id": lid, "text": text, "author": author, "now": now()})
    if about:
        g.query("""MATCH (l:Lesson {id: $id}) UNWIND $about AS x
                   OPTIONAL MATCH (p:Party {id: x}) OPTIONAL MATCH (a:Account {id: x})
                   WITH l, coalesce(p, a) AS n WHERE n IS NOT NULL
                   CREATE (l)-[:ABOUT]->(n)""", {"id": lid, "about": about})
    if refines:
        g.query("""MATCH (l:Lesson {id: $id}) MATCH (pb:Playbook {typology: $t}) CREATE (l)-[:REFINES]->(pb)""",
                {"id": lid, "t": refines})
    if case_id:
        g.query("""MATCH (l:Lesson {id: $id}) MATCH (c:Case {id: $c}) CREATE (l)-[:LEARNED_FROM]->(c)""",
                {"id": lid, "c": case_id})
    return lid


# ----------------------------------------------------------------------------- cases

def seed_closed_case(tenant: str, case: dict) -> None:
    g = db.graph(tenant)
    g.query("""CREATE (c:Case {id: $id, status: $status, disposition: $disp, opened: $opened, closed: $closed,
                               typologies: $typ, summary: $summary, analyst: $analyst, origin: 'history'})""",
            {"id": case["id"], "status": case["status"], "disp": case["disposition"], "opened": case["opened"],
             "closed": case["closed"], "typ": case["typologies"], "summary": case["summary"],
             "analyst": case["analyst"]})
    link_subjects(tenant, case["id"], case.get("subjects", []), case.get("accounts", []))
    if case.get("lesson"):
        add_lesson(tenant, case["lesson"], author=case["analyst"], about=case.get("subjects"),
                   refines=case["typologies"][0], case_id=case["id"])
    if case["disposition"] == "SAR_FILED":
        g.query("""MATCH (c:Case {id: $id}) CREATE (s:SAR {id: $sid, status: 'FILED', filed: $closed,
                   narrative: $summary})-[:FOR_CASE]->(c)""",
                {"id": case["id"], "sid": case["id"].replace("CASE", "SAR"), "closed": case["closed"],
                 "summary": case["summary"]})


def link_subjects(tenant: str, case_id: str, parties: list[str], accounts: list[str]) -> None:
    g = db.graph(tenant)
    if parties:
        g.query("""MATCH (c:Case {id: $c}) UNWIND $ids AS x MATCH (p:Party {id: x})
                   MERGE (c)-[:SUBJECT]->(p)""", {"c": case_id, "ids": parties})
    if accounts:
        g.query("""MATCH (c:Case {id: $c}) UNWIND $ids AS x MATCH (a:Account {id: x})
                   MERGE (c)-[:CONCERNS]->(a)""", {"c": case_id, "ids": accounts})


def open_case(tenant: str, alert_ids: list[str], typology: str, priority: float) -> str:
    g = db.graph(tenant)
    cid = new_id("CASE")
    g.query("""CREATE (c:Case {id: $id, status: 'OPEN', opened: $now, typologies: [$t], priority: $p,
                               origin: 'hound'})""", {"id": cid, "now": now(), "t": typology, "p": priority})
    _attach(g, cid, alert_ids, merged=False, reason="")
    return cid


def attach_alerts(tenant: str, case_id: str, alert_ids: list[str], reason: str) -> int:
    return _attach(db.graph(tenant), case_id, alert_ids, merged=True, reason=reason)


def _attach(g, case_id: str, alert_ids: list[str], *, merged: bool, reason: str) -> int:
    res = g.query("""MATCH (c:Case {id: $c}) UNWIND $alerts AS aid MATCH (al:Alert {id: aid})
                     MERGE (c)-[r:FROM_ALERT]->(al)
                     SET r.merged = $merged, r.reason = $reason, r.at = $now, al.status = 'IN_CASE'
                     RETURN count(al) AS n""",
                  {"c": case_id, "alerts": alert_ids, "merged": merged, "reason": reason, "now": now()})
    g.query("""MATCH (c:Case {id: $c})-[:FROM_ALERT]->(:Alert)-[:ON]->(a:Account)
               MERGE (c)-[:CONCERNS]->(a)
               WITH c, a MATCH (p:Party)-[:HOLDS]->(a)
               MERGE (c)-[:SUBJECT]->(p)""", {"c": case_id})
    return res.result_set[0][0] if res.result_set else 0


def close_case(tenant: str, case_id: str, disposition: str, summary: str, risk_score: float,
               typologies: list[str]) -> None:
    db.graph(tenant).query("""MATCH (c:Case {id: $c})
        SET c.status = CASE WHEN $d = 'FALSE_POSITIVE' THEN 'CLOSED' ELSE 'PENDING_APPROVAL' END,
            c.disposition = $d, c.summary = $s, c.risk_score = $r, c.typologies = $t, c.decided = $now
        WITH c MATCH (c)-[:FROM_ALERT]->(al:Alert)
        SET al.status = CASE WHEN $d = 'FALSE_POSITIVE' THEN 'CLOSED_FP' ELSE 'ESCALATED' END""",
                           {"c": case_id, "d": disposition, "s": summary, "r": risk_score, "t": typologies, "now": now()})


# ----------------------------------------------------------------------------- evidence & findings

def record_evidence(tenant: str, case_id: str | None, run_id: str | None, tool: str, cypher: str,
                    params: dict, summary: str, entity_ids: list[str], row_count: int, ms: float,
                    data: Any = None, graph_json: str = "") -> str:
    g = db.graph(tenant)
    eid = new_id("EV")
    g.query("""CREATE (e:Evidence {id: $id, tool: $tool, cypher: $cypher, params: $params, summary: $summary,
                                   rows: $rows, ms: $ms, created: $now, data: $data, graph: $graph})""",
            {"id": eid, "tool": tool, "cypher": cypher.strip(), "params": json.dumps(params, default=str),
             "summary": summary[:2000], "rows": row_count, "ms": round(ms, 2), "now": now(),
             "data": json.dumps(data, default=str)[:30000], "graph": graph_json[:60000]})
    if case_id:
        g.query("MATCH (c:Case {id: $c}) MATCH (e:Evidence {id: $e}) CREATE (c)-[:HAS_EVIDENCE]->(e)",
                {"c": case_id, "e": eid})
    if run_id:
        g.query("MATCH (r:AgentRun {id: $r}) MATCH (e:Evidence {id: $e}) CREATE (r)-[:PRODUCED]->(e)",
                {"r": run_id, "e": eid})
    ids = list(dict.fromkeys(entity_ids))[:60]
    if ids:
        g.query("""MATCH (e:Evidence {id: $e}) UNWIND $ids AS x
                   OPTIONAL MATCH (p:Party {id: x}) OPTIONAL MATCH (a:Account {id: x})
                   WITH e, coalesce(p, a) AS n WHERE n IS NOT NULL
                   MERGE (e)-[:INVOLVES]->(n)""", {"e": eid, "ids": ids})
    return eid


def record_finding(tenant: str, case_id: str, run_id: str | None, typology: str, claim: str,
                   severity: str, confidence: float, evidence_ids: list[str]) -> dict:
    g = db.graph(tenant)
    valid, _ = db.rows(g, """MATCH (c:Case {id: $c})-[:HAS_EVIDENCE]->(e:Evidence) WHERE e.id IN $ids
                             RETURN collect(e.id) AS ids""", {"c": case_id, "ids": evidence_ids})
    valid_ids = valid[0]["ids"] if valid else []
    missing = [e for e in evidence_ids if e not in valid_ids]
    if not valid_ids:
        return {"ok": False, "error": "A finding must cite at least one evidence id produced in this case.",
                "missing": missing}
    fid = new_id("FND")
    g.query("""MATCH (c:Case {id: $c})
               CREATE (c)-[:HAS_FINDING]->(f:Finding {id: $id, typology: $t, claim: $claim, severity: $sev,
                                                        confidence: $conf, created: $now})
               WITH f UNWIND $ev AS eid MATCH (e:Evidence {id: eid}) CREATE (f)-[:SUPPORTED_BY]->(e)""",
            {"c": case_id, "id": fid, "t": typology, "claim": claim, "sev": severity,
             "conf": float(confidence), "now": now(), "ev": valid_ids})
    if run_id:
        g.query("MATCH (r:AgentRun {id: $r}) MATCH (f:Finding {id: $f}) CREATE (r)-[:PRODUCED]->(f)",
                {"r": run_id, "f": fid})
    return {"ok": True, "finding_id": fid, "cited": valid_ids, "ignored": missing}


# ----------------------------------------------------------------------------- agent runs & handoffs

def start_run(tenant: str, case_id: str, agent: str, model: str, mode: str,
              handoff_from: str | None = None, note: str = "") -> str:
    g = db.graph(tenant)
    rid = new_id("RUN")
    g.query("""MATCH (c:Case {id: $c})
               CREATE (r:AgentRun {id: $id, agent: $agent, model: $model, mode: $mode, started: $started,
                                   status: 'RUNNING'})-[:WORKED_ON]->(c)""",
            {"c": case_id, "id": rid, "agent": agent, "model": model, "mode": mode, "started": round(time.time(), 3)})
    if handoff_from:
        g.query("""MATCH (a:AgentRun {id: $a}) MATCH (b:AgentRun {id: $b})
                   CREATE (a)-[:HANDOFF {note: $note, at: $now}]->(b)""",
                {"a": handoff_from, "b": rid, "note": note, "now": now()})
    return rid


def finish_run(tenant: str, run_id: str, status: str, usage: dict | None = None) -> None:
    usage = usage or {}
    db.graph(tenant).query("""MATCH (r:AgentRun {id: $r}) SET r.status = $s, r.ended = $now,
                              r.input_tokens = $i, r.output_tokens = $o, r.tool_calls = $t""",
                           {"r": run_id, "s": status, "now": now(), "i": usage.get("input_tokens", 0),
                            "o": usage.get("output_tokens", 0), "t": usage.get("tool_calls", 0)})


# ----------------------------------------------------------------------------- recall

def recall(tenant: str, ids: list[str]) -> dict[str, Any]:
    """Prior cases and lessons on these entities, and on entities linked to them in the graph."""
    g = db.graph(tenant)
    direct, _ = db.rows(g, """
        UNWIND $ids AS x
        OPTIONAL MATCH (p:Party {id: x}) OPTIONAL MATCH (a:Account {id: x})
        WITH x, coalesce(p, a) AS n WHERE n IS NOT NULL
        MATCH (c:Case)-[:SUBJECT|CONCERNS]->(n)
        RETURN DISTINCT c.id AS case_id, c.status AS status, c.disposition AS disposition,
               c.typologies AS typologies, c.summary AS summary, c.opened AS opened, x AS via""", {"ids": ids})
    linked, _ = db.rows(g, """
        UNWIND $ids AS x
        MATCH (p:Party {id: x})-[:USES|LOGGED_IN_FROM|HAS_PHONE|LIVES_AT]->(i)<-[:USES|LOGGED_IN_FROM|HAS_PHONE|LIVES_AT]-(q:Party)
        WHERE q.id <> x
        MATCH (c:Case)-[:SUBJECT]->(q)
        RETURN DISTINCT c.id AS case_id, c.status AS status, c.disposition AS disposition,
               c.typologies AS typologies, c.summary AS summary, q.id AS linked_party, labels(i)[0] AS shared,
               x AS via LIMIT 20""", {"ids": ids})
    lessons, _ = db.rows(g, """
        UNWIND $ids AS x
        OPTIONAL MATCH (p:Party {id: x}) OPTIONAL MATCH (a:Account {id: x})
        WITH x, coalesce(p, a) AS n WHERE n IS NOT NULL
        OPTIONAL MATCH (h:Party)-[:HOLDS]->(n)
        WITH x, [n] + collect(h) AS targets UNWIND targets AS t
        MATCH (l:Lesson)-[:ABOUT]->(t)
        RETURN DISTINCT l.id AS lesson_id, l.text AS text, l.author AS author, t.id AS about""", {"ids": ids})
    def dedupe(items: list[dict], key: str) -> list[dict]:
        seen, out = set(), []
        for it in items:
            if it[key] not in seen:
                seen.add(it[key])
                out.append(it)
        return out
    return {"direct_cases": dedupe(direct, "case_id"), "linked_cases": dedupe(linked, "case_id"),
            "lessons": dedupe(lessons, "lesson_id")}


def open_case_touching(tenant: str, account_ids: list[str], exclude: str | None = None) -> list[dict]:
    """Open Hound cases that already cover these accounts or their identity cluster (for de-duplication)."""
    g = db.graph(tenant)
    found, _ = db.rows(g, """
        UNWIND $ids AS x MATCH (a:Account {id: x})
        OPTIONAL MATCH (c1:Case)-[:CONCERNS]->(a)
        OPTIONAL MATCH (a)<-[:HOLDS]-(:Party)-[:USES|LOGGED_IN_FROM]->(i)<-[:USES|LOGGED_IN_FROM]-(:Party)<-[:SUBJECT]-(c2:Case)
        WITH x, collect(DISTINCT c1) + collect(DISTINCT c2) AS cs UNWIND cs AS c
        WITH x, c WHERE c IS NOT NULL AND c.origin = 'hound' AND c.status <> 'CLOSED' AND c.id <> $ex
        RETURN DISTINCT c.id AS case_id, c.status AS status, c.typologies AS typologies, x AS via""",
                        {"ids": account_ids, "ex": exclude or ""})
    return found
