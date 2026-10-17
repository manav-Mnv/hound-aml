"""Runs the agent pipeline for an alert and records every handoff in the graph.

triage run -> investigator run -> (escalated) SAR writer run -> reviewer run -> human decision
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from collections import deque
from typing import Callable

import anthropic

from . import agents, consortium, db, memory, offline, tools, triage
from .config import settings

Emit = Callable[[dict], None]
_live_runs: deque[float] = deque()
_lock = threading.Lock()


def _llm_allowed(mode: str) -> bool:
    if mode == "offline" or not settings.has_llm:
        return False
    with _lock:
        cutoff = time.time() - 3600
        while _live_runs and _live_runs[0] < cutoff:
            _live_runs.popleft()
        if len(_live_runs) >= settings.live_runs_per_hour:
            return False
        _live_runs.append(time.time())
        return True


def investigate(tenant: str, alert_id: str, emit: Emit, mode: str = "auto") -> dict:
    queue = {a["id"]: a for a in triage.queue(tenant)}
    alert = queue.get(alert_id)
    if alert is None:
        raise ValueError(f"alert {alert_id} not found")
    if alert.get("score") is None:
        triage.score_alerts(tenant)
        queue = {a["id"]: a for a in triage.queue(tenant)}
        alert = queue[alert_id]
    if alert.get("case_id"):
        emit({"type": "info", "agent": "orchestrator", "text": f"{alert_id} is already part of {alert['case_id']}."})
        return {"case_id": alert["case_id"], "existing": True}

    existing = memory.open_case_touching(tenant, [alert["account"]])
    if existing:
        cid = existing[0]["case_id"]
        memory.attach_alerts(tenant, cid, [alert_id], "Account already covered by an open case")
        emit({"type": "merged", "agent": "orchestrator", "case_id": cid,
              "text": f"Memory: {alert['account']} is already under investigation in {cid}; alert attached instead of opening a duplicate case."})
        return {"case_id": cid, "merged": True}

    group = [a for a in queue.values() if a.get("grp") == alert.get("grp") and not a.get("case_id")]
    case_id = memory.open_case(tenant, [alert_id], alert["typology"], (alert.get("score") or 0) / 100)
    emit({"type": "case_opened", "agent": "orchestrator", "case_id": case_id, "alert": alert, "group": group})

    triage_run = memory.start_run(tenant, case_id, "triage", "graph-features", "deterministic")
    memory.finish_run(tenant, triage_run, "DONE")
    emit({"type": "agent_done", "agent": "triage", "text": f"Triage score {alert['score']}/100", "reasons": alert.get("reasons")})

    use_llm = _llm_allowed(mode)
    inv_mode = "llm" if use_llm else "offline"
    inv_run = memory.start_run(tenant, case_id, "investigator", settings.model if use_llm else "playbook", inv_mode,
                               triage_run, f"Triage score {alert['score']}; {len(group)} grouped alert(s).")
    emit({"type": "handoff", "from": "triage", "to": "investigator", "run_id": inv_run, "mode": inv_mode})
    ctx = tools.ToolContext(tenant, case_id, inv_run, emit)
    playbook = memory.playbook(tenant, alert["typology"])
    result: dict = {}
    try:
        if use_llm:
            result = agents.run_investigator(ctx, alert, group, playbook, emit)
    except (anthropic.APIError, anthropic.APIConnectionError) as exc:
        emit({"type": "warning", "agent": "investigator", "text": f"Claude unavailable ({type(exc).__name__}); switching to playbook mode."})
        result = {}
    if not result.get("disposition"):
        if use_llm:
            inv_mode = "offline"
            emit({"type": "warning", "agent": "investigator", "text": "No disposition from the model; completing with the playbook runner."})
        result = offline.run_offline(ctx, alert, group, playbook, emit)
    memory.finish_run(tenant, inv_run, "DONE", result.get("usage"))
    disp = result["disposition"]
    emit({"type": "disposition", "agent": "investigator", "disposition": disp})

    sar = None
    if disp.get("disposition") in ("SAR_RECOMMENDED", "ESCALATE_SAR"):
        try:
            sar = agents.run_sar_pipeline(tenant, case_id, inv_run, emit) if use_llm and inv_mode == "llm" else \
                offline.run_offline_sar(tenant, case_id, inv_run, emit)
        except Exception as exc:
            emit({"type": "warning", "agent": "sar_writer", "text": f"SAR drafting failed ({exc}); using template draft."})
            sar = offline.run_offline_sar(tenant, case_id, inv_run, emit)
    detail = case_detail(tenant, case_id)
    emit({"type": "case_done", "agent": "orchestrator", "case_id": case_id, "case": detail["case"]})
    return {"case_id": case_id, "disposition": disp, "sar": sar and {k: sar[k] for k in ("sar_id", "review", "revisions")}}


def decide(tenant: str, case_id: str, decision: str, analyst: str, note: str = "") -> dict:
    """Human in the loop: the analyst approves or overrides. Overrides become lessons (procedural memory)."""
    g = db.graph(tenant)
    case = case_detail(tenant, case_id)["case"]
    published = []
    if decision == "approve_sar":
        g.query("""MATCH (c:Case {id: $c}) SET c.status = 'CLOSED', c.disposition = 'SAR_FILED', c.closed = $now,
                   c.analyst = $a
                   WITH c OPTIONAL MATCH (s:SAR)-[:FOR_CASE]->(c) SET s.status = 'FILED', s.filed = $now, s.approved_by = $a
                   WITH c MATCH (c)-[:FROM_ALERT]->(al:Alert) SET al.status = 'SAR_FILED'""",
                {"c": case_id, "now": memory.now(), "a": analyst})
        idents, _ = db.rows(g, """MATCH (c:Case {id: $c})-[:SUBJECT]->(p:Party)-[:USES|HAS_PHONE|LOGGED_IN_FROM]->(i)
                                  RETURN DISTINCT labels(i)[0] AS label, coalesce(i.fingerprint, i.number, i.addr) AS value""",
                             {"c": case_id})
        kinds = {"Device": "device", "Phone": "phone", "IP": "ip"}
        for i in idents:
            if i["value"] and not i["value"].startswith("2001:db8"):
                consortium.publish(tenant, kinds[i["label"]], i["value"], typology=(case.get("typologies") or ["OTHER"])[0],
                                   case_id=case_id)
                published.append(kinds[i["label"]])
    elif decision in ("close_false_positive", "reject_sar"):
        g.query("""MATCH (c:Case {id: $c}) SET c.status = 'CLOSED', c.disposition = 'FALSE_POSITIVE', c.closed = $now,
                   c.analyst = $a, c.override = $o
                   WITH c MATCH (c)-[:FROM_ALERT]->(al:Alert) SET al.status = 'CLOSED_FP'""",
                {"c": case_id, "now": memory.now(), "a": analyst, "o": decision == "reject_sar"})
    elif decision == "reopen_escalate":
        g.query("""MATCH (c:Case {id: $c}) SET c.status = 'PENDING_APPROVAL', c.disposition = 'SAR_RECOMMENDED',
                   c.analyst = $a, c.override = true""", {"c": case_id, "a": analyst})
    else:
        raise ValueError(f"unknown decision {decision}")
    lesson = None
    if note.strip():
        subjects = [s["id"] for s in case.get("subjects", []) if s.get("id")]
        typ = (case.get("typologies") or [None])[0]
        lesson = memory.add_lesson(tenant, note.strip(), author=analyst, about=subjects,
                                   refines=typ if typ in memory.PLAYBOOKS else None, case_id=case_id)
    return {"ok": True, "case_id": case_id, "decision": decision, "published_to_consortium": published, "lesson_id": lesson}


def case_detail(tenant: str, case_id: str) -> dict:
    g = db.graph(tenant)
    case, _ = db.rows(g, """MATCH (c:Case {id: $c})
        OPTIONAL MATCH (c)-[:SUBJECT]->(p:Party)
        WITH c, collect(DISTINCT {id: p.id, name: p.name, type: CASE WHEN p:Company THEN 'Company' ELSE 'Person' END}) AS subjects
        OPTIONAL MATCH (c)-[:CONCERNS]->(a:Account)
        WITH c, subjects, collect(DISTINCT a.id) AS accounts
        OPTIONAL MATCH (c)-[fa:FROM_ALERT]->(al:Alert)
        RETURN c.id AS id, c.status AS status, c.disposition AS disposition, c.summary AS summary,
               c.typologies AS typologies, c.risk_score AS risk_score, c.recommended_actions AS actions,
               c.opened AS opened, c.decided AS decided, c.origin AS origin, subjects, accounts,
               collect(DISTINCT {id: al.id, rule: al.rule_name, merged: fa.merged, reason: fa.reason}) AS alerts""",
                       {"c": case_id})
    if not case:
        raise ValueError(f"case {case_id} not found")
    findings, _ = db.rows(g, """MATCH (c:Case {id: $c})-[:HAS_FINDING]->(f:Finding)
                                OPTIONAL MATCH (f)-[:SUPPORTED_BY]->(e:Evidence)
                                RETURN f.id AS id, f.typology AS typology, f.claim AS claim, f.severity AS severity,
                                       f.confidence AS confidence, collect(e.id) AS evidence, f.created AS created ORDER BY created""", {"c": case_id})
    evidence, _ = db.rows(g, """MATCH (c:Case {id: $c})-[:HAS_EVIDENCE]->(e:Evidence)
                                RETURN e.id AS id, e.tool AS tool, e.summary AS summary, e.cypher AS cypher,
                                       e.params AS params, e.ms AS ms, e.rows AS rows, e.graph AS graph, e.created AS created
                                ORDER BY created""", {"c": case_id})
    for e in evidence:
        e["graph"] = json.loads(e["graph"]) if e.get("graph") else {"nodes": [], "edges": []}
    runs, _ = db.rows(g, """MATCH (r:AgentRun)-[:WORKED_ON]->(:Case {id: $c})
                            OPTIONAL MATCH (r)-[h:HANDOFF]->(n:AgentRun)
                            RETURN r.id AS id, r.agent AS agent, r.model AS model, r.mode AS mode, r.status AS status,
                                   r.started AS started, r.ended AS ended, r.input_tokens AS input_tokens,
                                   r.output_tokens AS output_tokens, r.tool_calls AS tool_calls,
                                   collect({to: n.agent, note: h.note}) AS handoffs ORDER BY started""", {"c": case_id})
    sar, _ = db.rows(g, """MATCH (s:SAR)-[:FOR_CASE]->(:Case {id: $c})
                           RETURN s.id AS id, s.status AS status, s.title AS title, s.narrative AS narrative,
                                  s.review AS review, s.grounding AS grounding, s.mode AS mode, s.created AS created
                           ORDER BY created DESC LIMIT 1""", {"c": case_id})
    if sar:
        sar[0]["narrative"] = json.loads(sar[0]["narrative"]) if sar[0].get("narrative", "").startswith("{") else sar[0]["narrative"]
        sar[0]["review"] = json.loads(sar[0]["review"]) if sar[0].get("review") else None
    c = case[0]
    c["alerts"] = [a for a in c["alerts"] if a.get("id")]
    c["subjects"] = [s for s in c["subjects"] if s.get("id")]
    return {"case": c, "findings": findings, "evidence": evidence, "runs": runs, "sar": sar[0] if sar else None}


def list_cases(tenant: str) -> list[dict]:
    rows, _ = db.rows(db.graph(tenant), """
        MATCH (c:Case)
        OPTIONAL MATCH (c)-[:FROM_ALERT]->(al:Alert)
        OPTIONAL MATCH (c)-[:SUBJECT]->(p:Party)
        RETURN c.id AS id, c.status AS status, c.disposition AS disposition, c.typologies AS typologies,
               c.risk_score AS risk_score, c.opened AS opened, c.origin AS origin, count(DISTINCT al) AS alerts,
               collect(DISTINCT p.name) AS subjects
        ORDER BY opened DESC""")
    return rows


def safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        traceback.print_exc()
        raise
