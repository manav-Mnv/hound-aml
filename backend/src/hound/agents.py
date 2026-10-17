"""The agent crew. Each agent is a separate run recorded in the graph, and they hand work to each
other through the case they share:

  Triage (graph scoring)  ->  Investigator (Claude + graph tools)  ->  SAR writer (Claude, structured)
                                                                   ->  Reviewer (grounding check, revise loop)

When no API key is configured the investigator and SAR writer fall back to the offline playbook
runner in offline.py, which follows the same procedural memory (playbooks) stored in the graph.
"""
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from typing import Any, Callable

import anthropic

from . import db, memory, tools
from .config import settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"

INVESTIGATOR_TOOLS = [
    "get_alert", "customer_profile", "trace_money_flow", "pass_through_analysis", "find_cycles",
    "counterparty_summary", "cash_structuring_profile", "identity_cluster", "shared_identifiers",
    "corporate_network", "network_position", "peer_comparison", "sanctions_exposure", "screen_names",
    "recall_memory", "consortium_check", "run_cypher",
    "record_finding", "consolidate_alerts", "remember", "submit_disposition",
]

INVESTIGATOR_SYSTEM = """You are Hound, an anti-money-laundering investigations agent working inside {bank}'s graph \
database (FalkorDB). An alert from the bank's rule-based transaction monitoring has been assigned to you. Investigate it \
the way an experienced BSA/AML investigator would, using the graph tools, and reach a disposition.

How to work:
- Start from memory: call recall_memory on the subject before anything else, and read the playbook steps and lessons in the \
brief. Lessons were written by analysts on earlier cases; take them seriously.
- Follow the money and the relationships. Most alerts are false positives; look for the legitimate explanation as hard \
as you look for the suspicious one, and say which one the evidence supports.
- Every factual claim must come from a tool result. Cite evidence ids exactly as returned (EV-XXXXXXXX). Never invent \
amounts, dates, names or ids.
- Record each material finding (suspicious or benign) with record_finding, citing its evidence ids.
- If you find other accounts in the same scheme (same ring, loop, or chain), call consolidate_alerts with their account ids \
so the bank works them as one case.
- If you learn something durable that would help future investigations (a pattern, a verified legitimate business model, \
a crew's signature), save it with remember, attached to the relevant entities.
- Finish by calling submit_disposition exactly once. ESCALATE_SAR only when findings support suspicion; \
CLOSE_FALSE_POSITIVE when the activity has a verified legitimate explanation; MONITOR_EDD when risk remains unresolved.
- Be efficient: usually 5-10 tool calls are enough. Call independent tools in parallel.

Domain notes: cash deposits over $10,000 require a CTR (31 CFR 1010.311); breaking deposits up to evade that is \
structuring (31 U.S.C. 5324). Under OFAC's 50 Percent Rule an entity owned 50% or more in aggregate, directly or \
indirectly, by blocked persons is itself blocked even if unlisted. Money mules typically are recently onboarded, share \
devices or IPs with other new accounts and forward most funds within hours. The jurisdictions XQ, XT and XV are \
fictional high-risk jurisdictions in this synthetic dataset. Write neutrally: describe facts, do not accuse."""

SAR_SYSTEM = """You draft the narrative section of a Suspicious Activity Report for {bank}, from an investigation that \
another agent completed. Follow FinCEN's narrative guidance: cover who, what, when, where, why and how, in a neutral \
factual tone, so the narrative stands on its own without attachments.

Hard rule: every sentence must cite one or more evidence ids from the list provided, and every number, date and name \
in a sentence must appear in the cited evidence. If something is not in the evidence, leave it out. Prefer short, \
specific sentences. Do not speculate about intent beyond what the evidence shows; say "appears consistent with" for \
typology conclusions."""

SAR_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subjects": {"type": "array", "items": {"type": "string"}},
        "typologies": {"type": "array", "items": {"type": "string"}},
        "activity_start": {"type": "string"},
        "activity_end": {"type": "string"},
        "total_suspicious_amount": {"type": "number"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string", "enum": ["Summary", "Who", "What", "When", "Where", "Why", "How",
                                                           "Actions taken"]},
                    "sentences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"text": {"type": "string"},
                                           "evidence_ids": {"type": "array", "items": {"type": "string"}}},
                            "required": ["text", "evidence_ids"], "additionalProperties": False,
                        },
                    },
                },
                "required": ["heading", "sentences"], "additionalProperties": False,
            },
        },
    },
    "required": ["title", "subjects", "typologies", "activity_start", "activity_end", "total_suspicious_amount",
                 "sections"],
    "additionalProperties": False,
}

Emit = Callable[[dict], None]


@lru_cache(maxsize=1)
def client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
    return anthropic.Anthropic(api_key=key, max_retries=3)


def call_claude(system: str, messages: list, *, tools_list: list | None = None, fmt: dict | None = None,
                effort: str | None = None, max_tokens: int = 16000):
    params: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system}],
        "messages": messages,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": effort or settings.effort},
        "cache_control": {"type": "ephemeral"},
    }
    if tools_list:
        params["tools"] = tools_list
    if fmt:
        params["output_config"]["format"] = fmt
    try:
        return client().beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
    except anthropic.BadRequestError as exc:
        if "fallback" not in str(exc).lower():
            raise
        return client().messages.create(**params)


def _usage_add(acc: dict, resp) -> None:
    u = getattr(resp, "usage", None)
    if not u:
        return
    acc["input_tokens"] = acc.get("input_tokens", 0) + (u.input_tokens or 0)
    acc["output_tokens"] = acc.get("output_tokens", 0) + (u.output_tokens or 0)
    acc["cache_read_tokens"] = acc.get("cache_read_tokens", 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)


def _bank(tenant: str) -> str:
    return db.TENANT_NAMES.get(tenant, tenant)


# ============================================================================ investigator

def investigator_brief(tenant: str, case_id: str, alert: dict, group: list[dict], playbook: dict) -> str:
    steps = "\n".join(f"  {i + 1}. {s['tool']}: {s['instruction']}" for i, s in enumerate(playbook["steps"]))
    lessons = "\n".join(f"  - {l['text']} ({l['author']})" for l in playbook["lessons"]) or "  - none yet"
    related = "\n".join(f"  - {g['id']} on {g['account']} ({g['holder']}): {g['rule_name']}, triage {g['score']}"
                        for g in group if g["id"] != alert["id"]) or "  - none"
    reasons = "\n".join(f"  {r}" for r in alert.get("reasons") or [])
    return f"""Case {case_id} at {_bank(tenant)}.

Alert {alert['id']} - {alert['rule_name']} ({alert['rule']}) on account {alert['account']} held by {alert['holder']} \
({alert['party']}, {alert['party_type']}).
Rule output: {alert['description']}
Triage score {alert['score']}/100 from graph features:
{reasons}

Other open alerts that triage grouped with this one (same identity cluster or direct money links):
{related}

Playbook for {playbook['typology']} (procedural memory from the graph):
{steps}
Playbook lessons:
{lessons}

Investigate and finish with submit_disposition."""


def run_investigator(ctx: tools.ToolContext, alert: dict, group: list[dict], playbook: dict, emit: Emit) -> dict:
    brief = investigator_brief(ctx.tenant, ctx.case_id, alert, group, playbook)
    emit({"type": "brief", "agent": "investigator", "text": brief})
    system = INVESTIGATOR_SYSTEM.format(bank=_bank(ctx.tenant))
    tool_defs = tools.anthropic_tools(INVESTIGATOR_TOOLS)
    messages: list[dict] = [{"role": "user", "content": brief}]
    usage: dict = {"tool_calls": 0}
    disposition: dict | None = None
    nudged = False
    for turn in range(settings.max_agent_turns):
        resp = call_claude(system, messages, tools_list=tool_defs)
        _usage_add(usage, resp)
        if resp.stop_reason == "refusal":
            emit({"type": "warning", "agent": "investigator", "text": "Model declined; falling back to playbook runner."})
            return {"disposition": None, "usage": usage, "refused": True}
        for block in resp.content:
            if block.type == "thinking" and getattr(block, "thinking", ""):
                emit({"type": "thinking", "agent": "investigator", "text": block.thinking})
            elif block.type == "text" and block.text.strip():
                emit({"type": "message", "agent": "investigator", "text": block.text})
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            if disposition or nudged or turn == settings.max_agent_turns - 1:
                break
            nudged = True
            messages.append({"role": "user", "content": "Record any remaining findings and finish with submit_disposition."})
            continue
        results = []
        for tu in uses:
            usage["tool_calls"] += 1
            out = tools.execute(ctx, tu.name, dict(tu.input))
            if tu.name == "submit_disposition" and out.get("ok"):
                disposition = {**dict(tu.input), **out}
            block = {"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out, default=str)[:14000]}
            if "error" in out:
                block["is_error"] = True
            results.append(block)
        messages.append({"role": "user", "content": results})
        if disposition:
            break
        if turn == settings.max_agent_turns - 2 and not disposition:
            messages.append({"role": "user", "content": "You are almost out of steps. Submit your disposition now."})
    return {"disposition": disposition, "usage": usage}


# ============================================================================ SAR writer + reviewer

def case_dossier(tenant: str, case_id: str) -> dict:
    g = db.graph(tenant)
    case, _ = db.rows(g, """MATCH (c:Case {id: $c})
                            OPTIONAL MATCH (c)-[:SUBJECT]->(p:Party)
                            OPTIONAL MATCH (c)-[:CONCERNS]->(a:Account)
                            RETURN c.id AS id, c.disposition AS disposition, c.summary AS rationale,
                                   c.typologies AS typologies, c.risk_score AS risk_score,
                                   c.recommended_actions AS actions,
                                   collect(DISTINCT {id: p.id, name: p.name, occupation: coalesce(p.occupation, p.industry),
                                                     onboarded: p.onboarded}) AS subjects,
                                   collect(DISTINCT a.id) AS accounts""", {"c": case_id})
    findings, _ = db.rows(g, """MATCH (c:Case {id: $c})-[:HAS_FINDING]->(f:Finding)
                                OPTIONAL MATCH (f)-[:SUPPORTED_BY]->(e:Evidence)
                                RETURN f.id AS id, f.typology AS typology, f.claim AS claim, f.severity AS severity,
                                       f.confidence AS confidence, collect(e.id) AS evidence, f.created AS created ORDER BY created""",
                          {"c": case_id})
    evidence, _ = db.rows(g, """MATCH (c:Case {id: $c})-[:HAS_EVIDENCE]->(e:Evidence)
                                RETURN e.id AS id, e.tool AS tool, e.summary AS summary, e.data AS data, e.created AS created
                                ORDER BY created""", {"c": case_id})
    return {"case": case[0] if case else {}, "findings": findings, "evidence": evidence}


def write_sar(tenant: str, case_id: str, emit: Emit, feedback: list[str] | None = None,
              previous: dict | None = None) -> tuple[dict, dict]:
    dossier = case_dossier(tenant, case_id)
    ev_lines = "\n".join(f"[{e['id']}] ({e['tool']}) {e['summary']}\n    data: {(e['data'] or '')[:1500]}"
                         for e in dossier["evidence"])
    finding_lines = "\n".join(f"- ({f['severity']}, {f['typology']}) {f['claim']} [{', '.join(f['evidence'])}]"
                              for f in dossier["findings"])
    prompt = f"""Case {case_id}: disposition {dossier['case'].get('disposition')}, typologies {dossier['case'].get('typologies')}.
Investigator rationale: {dossier['case'].get('rationale')}
Recommended actions: {dossier['case'].get('actions')}
Subjects: {json.dumps(dossier['case'].get('subjects'), default=str)}

Findings:
{finding_lines}

Evidence (the only facts you may use):
{ev_lines}

Draft the SAR narrative."""
    if feedback and previous:
        prompt += ("\n\nYour previous draft failed the grounding review. Fix every issue below by correcting the sentence, "
                   "citing the right evidence, or removing the sentence:\n- " + "\n- ".join(feedback)
                   + "\n\nPrevious draft:\n" + json.dumps(previous))
    usage: dict = {}
    resp = call_claude(SAR_SYSTEM.format(bank=_bank(tenant)), [{"role": "user", "content": prompt}],
                       fmt={"type": "json_schema", "schema": SAR_SCHEMA}, effort="medium")
    _usage_add(usage, resp)
    for block in resp.content:
        if block.type == "thinking" and getattr(block, "thinking", ""):
            emit({"type": "thinking", "agent": "sar_writer", "text": block.thinking})
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), usage


NUM_RE = re.compile(r"\$?\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\$\d+(?:\.\d+)?(?:k|K)?\b|\b\d{4,}(?:\.\d+)?\b")


ID_RE = re.compile(r"\b[A-Z]{1,6}(?:-[A-Z0-9]+)*-\d+\b|\b(?:SYN|REG)-[A-Z0-9-]+\b|\+1-\d{3}-555-\d{4}|\d+(?:\.\d+){3}")


def _numbers(text: str) -> list[float]:
    """Dollar amounts and large figures in a sentence (ids, phone numbers and IPs are ignored)."""
    text = ID_RE.sub(" ", text)
    out = []
    for m in NUM_RE.findall(text):
        raw = m.replace("$", "").replace(",", "")
        mult = 1000 if raw.lower().endswith("k") else 1
        raw = raw.rstrip("kK")
        try:
            val = float(raw) * mult
        except ValueError:
            continue
        if 1900 <= val <= 2100 and "." not in raw and "$" not in m:
            continue  # years
        if val >= 100:
            out.append(val)
    return out


def review_sar(tenant: str, case_id: str, sar: dict) -> dict:
    """Reviewer agent: every sentence must cite case evidence, and every amount must appear in it."""
    dossier = case_dossier(tenant, case_id)
    evidence = {e["id"]: (e["summary"] or "") + " " + (e["data"] or "") for e in dossier["evidence"]}
    issues, checked, grounded = [], 0, 0
    for sec in sar.get("sections", []):
        for s in sec.get("sentences", []):
            checked += 1
            cited = s.get("evidence_ids") or []
            unknown = [e for e in cited if e not in evidence]
            problems = []
            if not cited:
                problems.append("no evidence cited")
            if unknown:
                problems.append(f"cites evidence not in this case: {unknown}")
            hay = " ".join(evidence.get(e, "") for e in cited)
            hay_nums = _numbers(hay) + [float(x) for x in re.findall(r"\d+(?:\.\d+)?", hay) if float(x) >= 100]
            for n in _numbers(s.get("text", "")):
                if not any(abs(n - h) <= max(1.0, 0.015 * h) for h in hay_nums):
                    problems.append(f"amount {n:,.0f} not found in cited evidence")
            if problems:
                issues.append({"section": sec["heading"], "text": s.get("text", ""), "problems": problems})
            else:
                grounded += 1
    return {"sentences": checked, "grounded": grounded, "issues": issues,
            "score": round(grounded / checked, 3) if checked else 0.0}


def save_sar(tenant: str, case_id: str, sar: dict, review: dict, run_id: str | None, mode: str) -> str:
    g = db.graph(tenant)
    sid = memory.new_id("SAR")
    cited = sorted({e for sec in sar.get("sections", []) for s in sec.get("sentences", []) for e in s.get("evidence_ids", [])})
    g.query("""MATCH (c:Case {id: $c})
               CREATE (s:SAR {id: $id, status: 'DRAFT', title: $title, narrative: $narr, review: $review,
                              grounding: $score, created: $now, mode: $mode})-[:FOR_CASE]->(c)
               WITH s UNWIND $cited AS eid MATCH (e:Evidence {id: eid}) CREATE (s)-[:CITES]->(e)""",
            {"c": case_id, "id": sid, "title": sar.get("title", ""), "narr": json.dumps(sar), "review": json.dumps(review),
             "score": review["score"], "now": memory.now(), "mode": mode, "cited": cited})
    if run_id:
        g.query("MATCH (r:AgentRun {id: $r}) MATCH (s:SAR {id: $s}) CREATE (r)-[:PRODUCED]->(s)", {"r": run_id, "s": sid})
    return sid


def run_sar_pipeline(tenant: str, case_id: str, investigator_run: str, emit: Emit) -> dict:
    """SAR writer drafts, reviewer checks grounding, writer revises once if needed."""
    writer_run = memory.start_run(tenant, case_id, "sar_writer", settings.model, "llm", investigator_run,
                                  "Escalated: draft the SAR narrative from the case findings and evidence.")
    emit({"type": "handoff", "from": "investigator", "to": "sar_writer", "run_id": writer_run})
    sar, usage = write_sar(tenant, case_id, emit)
    emit({"type": "sar_draft", "agent": "sar_writer", "sar": sar})
    reviewer_run = memory.start_run(tenant, case_id, "reviewer", "grounding-check", "deterministic", writer_run,
                                    "Check every sentence against the cited evidence.")
    emit({"type": "handoff", "from": "sar_writer", "to": "reviewer", "run_id": reviewer_run})
    review = review_sar(tenant, case_id, sar)
    emit({"type": "review", "agent": "reviewer", "review": review})
    revisions = 0
    if review["issues"]:
        memory.finish_run(tenant, reviewer_run, "CHANGES_REQUESTED")
        emit({"type": "handoff", "from": "reviewer", "to": "sar_writer", "note": f"{len(review['issues'])} sentence(s) to fix"})
        feedback = [f"[{i['section']}] \"{i['text']}\": {'; '.join(i['problems'])}" for i in review["issues"]]
        sar, u2 = write_sar(tenant, case_id, emit, feedback, sar)
        for k, v in u2.items():
            usage[k] = usage.get(k, 0) + v
        revisions = 1
        review = review_sar(tenant, case_id, sar)
        emit({"type": "sar_draft", "agent": "sar_writer", "sar": sar, "revision": 1})
        emit({"type": "review", "agent": "reviewer", "review": review, "revision": 1})
    memory.finish_run(tenant, reviewer_run, "APPROVED" if not review["issues"] else "ISSUES_REMAIN")
    memory.finish_run(tenant, writer_run, "DONE", usage)
    sid = save_sar(tenant, case_id, sar, review, writer_run, "llm")
    return {"sar_id": sid, "sar": sar, "review": review, "revisions": revisions, "usage": usage}


def now_ms() -> int:
    return int(time.time() * 1000)
