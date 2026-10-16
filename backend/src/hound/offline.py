"""Offline investigator: walks the typology playbook stored in the graph (procedural memory),
applies explicit AML heuristics to the tool results, and writes findings that cite evidence.

Used when no Anthropic key is configured, when the model declines, and as the deterministic
baseline in the evaluation. It runs the same tools and writes the same graph records as the
LLM investigator, so the UI, memory and SAR pipeline behave identically.
"""
from __future__ import annotations

import re
from typing import Callable

from . import db, memory, tools
from .tools import HIGH_RISK_CODES, money

Emit = Callable[[dict], None]
WEIGHT = {"critical": 40, "high": 25, "medium": 12, "low": 5}
BENIGN_MEMO = re.compile(r"TUITION|PAYROLL|SALE PROCEEDS|CLOSING|ESTATE|BONUS|INV |INVOICE|WHOLESALE|RENT|LEASE", re.I)
BENIGN_INDUSTRY = {"Title & Escrow", "Employer", "Education", "Payroll Processing", "Grocery", "Card Settlement",
                   "Fisheries", "Property Management", "Utilities"}


class Run:
    def __init__(self, ctx: tools.ToolContext, alert: dict, emit: Emit):
        self.ctx, self.alert, self.emit = ctx, alert, emit
        self.out: dict[str, dict] = {}
        self.findings: list[dict] = []
        self.related_accounts: set[str] = set()

    def call(self, name: str, **args) -> dict:
        key = name if name not in self.out else f"{name}:{len(self.out)}"
        res = tools.execute(self.ctx, name, args)
        self.out[key] = res
        return res

    def find(self, typology: str, claim: str, severity: str, conf: float, *results: dict) -> None:
        ev = [r["evidence_id"] for r in results if r and r.get("evidence_id")]
        if not ev:
            return
        out = tools.execute(self.ctx, "record_finding", {"typology": typology, "claim": claim, "severity": severity,
                                                          "confidence": conf, "evidence_ids": ev})
        if out.get("ok"):
            self.findings.append({"typology": typology, "claim": claim, "severity": severity, "evidence": ev})


def _args_for(tool_name: str, alert: dict, typology: str) -> dict:
    acc, party = alert["account"], alert["party"]
    return {
        "recall_memory": {"entity_ids": [party, acc], "typology": typology},
        "cash_structuring_profile": {"account_id": acc},
        "trace_money_flow": {"account_id": acc, "direction": "out"},
        "identity_cluster": {"party_id": party}, "shared_identifiers": {"party_id": party},
        "consortium_check": {"party_id": party}, "screen_names": {"party_id": party},
        "peer_comparison": {"party_id": party}, "corporate_network": {"party_id": party},
        "pass_through_analysis": {"account_id": acc}, "find_cycles": {"account_id": acc},
        "counterparty_summary": {"account_id": acc}, "network_position": {"account_id": acc},
        "sanctions_exposure": {"entity_id": acc},
    }[tool_name]


def run_offline(ctx: tools.ToolContext, alert: dict, group: list[dict], playbook: dict, emit: Emit) -> dict:
    r = Run(ctx, alert, emit)
    typ = playbook["typology"]
    emit({"type": "message", "agent": "investigator",
          "text": f"Offline playbook mode: following the {typ} playbook from procedural memory ({len(playbook['steps'])} steps)."})
    profile = r.call("customer_profile", entity_id=alert["party"])
    for step in playbook["steps"]:
        r.call(step["tool"], **_args_for(step["tool"], alert, typ))
    _follow_ups(r, alert)
    _assess(r, alert, profile)
    sus = sum(WEIGHT[f["severity"]] for f in r.findings if f["typology"] != "BENIGN_EXPLANATION")
    ben = sum(WEIGHT[f["severity"]] for f in r.findings if f["typology"] == "BENIGN_EXPLANATION")
    to_merge = sorted(r.related_accounts - {alert["account"]})
    if to_merge and sus >= 35 and sus > ben:
        tools.execute(ctx, "consolidate_alerts", {"account_ids": to_merge,
                                                  "reason": "Same scheme: linked by shared identifiers or money flow in the graph"})
    typologies = sorted({f["typology"] for f in r.findings if f["typology"] != "BENIGN_EXPLANATION"}) or [typ]
    if sus >= 35 and sus > ben:
        disp, actions = "ESCALATE_SAR", ["File SAR within 30 days", "Review relationship for exit", "Share identifiers via 314(b)"]
    elif sus >= 15 and sus > ben:
        disp, actions = "MONITOR_EDD", ["Enhanced due diligence: request source of funds", "Re-review in 30 days"]
    else:
        disp, actions = "CLOSE_FALSE_POSITIVE", ["Close alert", "No further action"]
    claims = [f for f in r.findings if (f["typology"] == "BENIGN_EXPLANATION") == (disp == "CLOSE_FALSE_POSITIVE")] or r.findings
    rationale = " ".join(f"{f['claim']} [{', '.join(f['evidence'])}]" for f in claims[:5]) or \
        "No suspicious pattern found in the graph context; activity is consistent with the customer profile."
    risk = min(100, sus) if disp != "CLOSE_FALSE_POSITIVE" else max(0, min(30, sus - ben + 10))
    out = tools.execute(ctx, "submit_disposition", {"disposition": disp, "typologies": typologies, "risk_score": risk,
                                                    "rationale": rationale, "recommended_actions": actions})
    return {"disposition": {"disposition": disp, "typologies": typologies, "risk_score": risk, "rationale": rationale,
                            "recommended_actions": actions, **out},
            "usage": {"tool_calls": len(r.out)}}


def _follow_ups(r: Run, alert: dict) -> None:
    """Agent-like branching: what the first results suggest checking next."""
    have = set(k.split(":")[0] for k in r.out)
    data = {k.split(":")[0]: v.get("data") for k, v in r.out.items()}
    cyc = (data.get("find_cycles") or {}).get("cycles") or []
    if cyc and "corporate_network" not in have:
        r.call("corporate_network", party_id=alert["party"])
    if "counterparty_summary" not in have:
        r.call("counterparty_summary", account_id=alert["account"])
    clus = (data.get("identity_cluster") or {}).get("members") or []
    if len(clus) >= 3 and "consortium_check" not in have:
        r.call("consortium_check", party_id=alert["party"])
    if alert["rule"] in ("R5",) and "sanctions_exposure" not in have:
        r.call("sanctions_exposure", entity_id=alert["account"])


def _assess(r: Run, alert: dict, profile: dict) -> None:
    get = lambda k: r.out.get(k) or {}
    dat = lambda k: get(k).get("data") or {}
    prof = profile.get("data") or {}
    tenure = prof.get("tenure_days") or 0

    # -------- memory
    mem = dat("recall_memory")
    fps = [c for c in mem.get("direct_cases", []) if c.get("disposition") == "FALSE_POSITIVE"]
    if fps:
        r.find("BENIGN_EXPLANATION", f"Prior case {fps[0]['case_id']} on this customer was closed as a false positive: "
                                     f"{fps[0].get('summary', '')}", "high", 0.8, get("recall_memory"))
    sar_linked = [c for c in mem.get("linked_cases", []) if c.get("disposition") in ("SAR_FILED", "SAR_RECOMMENDED")]
    if sar_linked:
        r.find("MONEY_MULE", f"A party sharing a {sar_linked[0]['shared']} with the subject is the subject of case "
                             f"{sar_linked[0]['case_id']}.", "high", 0.75, get("recall_memory"))

    # -------- cash
    cash = dat("cash_structuring_profile")
    if cash:
        smurfs = cash.get("linked_depositors") or []
        if isinstance(smurfs, list) and len([s for s in smurfs if isinstance(s, dict)]) >= 2:
            sm = [s for s in smurfs if isinstance(s, dict)]
            r.related_accounts.update(s["account"] for s in sm)
            r.find("STRUCTURING", f"{len(sm)} linked depositors deposited {money(sum(s['cash_in'] for s in sm))} in cash "
                                  f"and forwarded {money(sum(s['forwarded'] for s in sm))} to {alert['account']} within 48 hours.",
                   "high", 0.85, get("cash_structuring_profile"))
        band, ctr, n = cash.get("bands", {}).get("8k_10k", 0), cash.get("ctr_filed_deposits", 0), cash.get("deposits", 0)
        if n >= 4 and band / max(n, 1) >= 0.5 and ctr == 0:
            r.find("STRUCTURING", f"{band} of {n} cash deposits fall between $8,000 and $10,000 and none exceed $10,000, "
                                  f"across {len(cash.get('branches_used', []))} branches.", "high", 0.8, get("cash_structuring_profile"))
        elif ctr >= max(1, band // 2):
            r.find("BENIGN_EXPLANATION", f"The customer regularly deposits more than $10,000 ({ctr} CTR-filed deposits vs "
                                         f"{band} in the $8k-$10k band), which is inconsistent with avoiding the CTR threshold.",
                   "medium", 0.7, get("cash_structuring_profile"))

    # -------- identity / mule
    clus = dat("identity_cluster")
    members = [m for m in clus.get("members", []) if isinstance(m, dict)]
    new = [m for m in members if (m.get("tenure_days") or 9999) <= 90]
    if len(members) >= 4 and len(new) >= len(members) / 2:
        for m in members:
            r.related_accounts.update(m.get("accounts") or [])
        shared = ", ".join(f"{s['type']} {s['value']}" for s in clus.get("shared_identifiers", [])[:3] if isinstance(s, dict))
        r.find("MONEY_MULE", f"The subject is one of {len(members)} parties in a WCC identity cluster linked by {shared}; "
                             f"{len(new)} were onboarded in the last 90 days.", "high", 0.85, get("identity_cluster"))
    cons = dat("consortium_check")
    hits = [h for h in cons.get("matches", []) if isinstance(h, dict)]
    if hits:
        r.find("MONEY_MULE", f"{len(hits)} of the subject's identifiers were reported to the consortium by "
                             f"{hits[0]['institution']} for {hits[0]['typology']} ({', '.join(h['kind'] for h in hits)}).",
               "critical", 0.9, get("consortium_check"))

    # -------- velocity / flow
    pt = dat("pass_through_analysis")
    if pt and pt.get("inflow", 0) >= 5000 and pt.get("share_out_within_48h", 0) >= 0.85:
        benign_cp = [b for b in pt.get("beneficiaries", []) if isinstance(b, dict) and b.get("holder") and
                     any(w in (b.get("holder") or "") for w in ("Title", "Escrow", "Settlement"))]
        if benign_cp:
            r.find("BENIGN_EXPLANATION", f"Funds moved on within 48 hours to {benign_cp[0]['holder']}, a title/escrow "
                                         f"company, consistent with a property transaction.", "medium", 0.7, get("pass_through_analysis"))
        else:
            r.find("LAYERING" if not members else "MONEY_MULE",
                   f"{pt['share_out_within_48h']:.0%} of {money(pt['inflow'])} received left within 48 hours (median dwell "
                   f"{pt.get('median_dwell_hours')}h); the top beneficiary received {pt.get('top_beneficiary_share', 0):.0%} of outflows.",
                   "medium", 0.7, get("pass_through_analysis"))
    tr = dat("trace_money_flow")
    paths = [p for p in tr.get("paths", []) if isinstance(p, dict)]
    risky = [p for p in paths if any(f", {c}]" in p["route"] for c in HIGH_RISK_CODES)]
    deep_risky = [p for p in risky if len(p["amounts"]) >= 2 and p["hours_end_to_end"] <= 72]
    if deep_risky:
        for dp in deep_risky:
            r.related_accounts.update(re.findall(r"\[(AC-\d+)", dp["route"]))
        p = deep_risky[0]
        r.find("LAYERING", f"Funds moved {len(p['amounts'])} hops in {p['hours_end_to_end']} hours to a high-risk "
                           f"jurisdiction: {p['route']}.", "high", 0.8, get("trace_money_flow"))
    elif risky and alert["rule"] != "R5":
        p = risky[0]
        r.find("LAYERING", f"Outbound funds reached a high-risk jurisdiction: {p['route']} ({money(sum(p['amounts']))}).",
               "medium", 0.6, get("trace_money_flow"))

    cyc = [c for c in dat("find_cycles").get("cycles", []) if isinstance(c, dict)]
    if cyc:
        c = cyc[0]
        r.find("ROUND_TRIPPING", f"{len(cyc)} closed transfer loop(s) return funds to the subject, e.g. {c['route']} "
                                 f"closing in {c['days_to_close']} days with {c['value_returned']:.0%} of value returned.",
               "high", 0.85, get("find_cycles"))
    corp = dat("corporate_network")
    sibs = [s for s in corp.get("siblings", []) if isinstance(s, dict)]
    if len(sibs) >= 2:
        r.find("SHELL_COMPANIES", f"{corp['company']['name']} shares officers or a registered address with {len(sibs)} other "
                                  f"companies: {', '.join(s['name'] for s in sibs[:4])}.", "medium", 0.7, get("corporate_network"))
    if cyc:
        r.related_accounts.update(_cycle_accounts(r))

    # -------- sanctions
    sx = dat("sanctions_exposure")
    for res in [x for x in sx.get("results", []) if isinstance(x, dict)]:
        if res["status"] in ("BLOCKED_50_RULE", "LISTED"):
            chain = "; ".join(f"{c['owner']} {c['pct']}%" for c in res["blocked_owner_chains"])
            r.find("SANCTIONS_EVASION", f"Counterparty {res['counterparty']} is blocked under the OFAC 50% rule: "
                                        f"{res['aggregate_blocked_ownership_pct']}% aggregate ownership by blocked persons ({chain}); "
                                        f"{money(res['value_transacted'])} transacted.", "critical", 0.9, get("sanctions_exposure"))
        elif res["status"] == "PARTIAL_EXPOSURE":
            r.find("SANCTIONS_EVASION", f"Counterparty {res['counterparty']} is {res['aggregate_blocked_ownership_pct']}% owned "
                                        f"by blocked persons: below the 50% threshold, but warrants enhanced due diligence.",
                   "low", 0.6, get("sanctions_exposure"))

    # -------- benign context for the noisy rules
    cp = dat("counterparty_summary")
    ins = [x for x in cp.get("inbound", []) if isinstance(x, dict)]
    outs = [x for x in cp.get("outbound", []) if isinstance(x, dict)]
    if alert["rule"] == "R3" and ins:
        small = [x for x in ins if x["total"] <= 1500]
        if len(small) >= len(ins) * 0.7 and (not pt or pt.get("share_out_within_48h", 0) < 0.5):
            r.find("BENIGN_EXPLANATION", f"{len(small)} of {len(ins)} senders made small payments (largest "
                                         f"{money(max(x['total'] for x in ins))}) and the funds stayed in the account, consistent "
                                         f"with gifts or group collections.", "medium", 0.65, get("counterparty_summary"))
    if alert["rule"] in ("R5", "R6"):
        memo_hits = [x for x in ins + outs if any(BENIGN_MEMO.search(m or "") for m in x.get("memos", []))
                     and (x.get("business") in BENIGN_INDUSTRY or x.get("business") in ("Seafood Import",))]
        sanctions_bad = any(f["typology"] == "SANCTIONS_EVASION" and f["severity"] == "critical" for f in r.findings)
        if memo_hits and not sanctions_bad:
            x = memo_hits[0]
            r.find("BENIGN_EXPLANATION", f"The large flow is with {x['name']} ({x['business']}) with memos "
                                         f"{', '.join(x['memos'][:2])}, consistent with the stated purpose.", "medium", 0.65,
                   get("counterparty_summary"))
        elif alert["rule"] == "R5" and tenure > 1500 and not sanctions_bad and outs and \
                len([o for o in outs if o["country"] in HIGH_RISK_CODES and o["n"] >= 3]) >= 1:
            o = [o for o in outs if o["country"] in HIGH_RISK_CODES][0]
            r.find("BENIGN_EXPLANATION", f"Established customer ({tenure // 365} years) making regular payments to "
                                         f"{o['name']} ({o['n']} payments, memos {', '.join(o['memos'][:2])}).", "medium", 0.6,
                   get("counterparty_summary"))
    sn = dat("screen_names")
    for h in [x for x in sn.get("hits", []) if isinstance(x, dict)]:
        if h.get("birth_year_match") is False and h.get("country_match") is False:
            r.find("BENIGN_EXPLANATION", f"Name similarity to designated {h['name']} ({h['list_id']}) is a namesake: birth "
                                         f"year and country do not match.", "low", 0.7, get("screen_names"))


def _cycle_accounts(r: Run) -> set[str]:
    out = set()
    for k, v in r.out.items():
        if k.startswith("find_cycles"):
            ev = v.get("evidence_id")
            if ev:
                rows, _ = db.rows(db.graph(r.ctx.tenant), "MATCH (:Evidence {id: $e})-[:INVOLVES]->(a:Account) RETURN collect(a.id) AS ids",
                                  {"e": ev})
                out.update(rows[0]["ids"] if rows else [])
    return out


def offline_sar(tenant: str, case_id: str) -> dict:
    """Template SAR narrative built only from recorded findings (each sentence keeps its citations)."""
    from .agents import case_dossier
    d = case_dossier(tenant, case_id)
    case = d["case"]
    subjects = [s for s in case.get("subjects", []) if s.get("id")]
    sus = [f for f in d["findings"] if f["typology"] != "BENIGN_EXPLANATION"]
    first_ev = sus[0]["evidence"] if sus else [e["id"] for e in d["evidence"][:1]]
    names = ", ".join(f"{s['name']} ({s['id']})" for s in subjects[:8])
    sections = [
        {"heading": "Summary", "sentences": [{"text": f"{_bank_name(tenant)} is reporting activity by {len(subjects)} subject(s) that appears "
                                                     f"consistent with {', '.join(t.lower().replace('_', ' ') for t in case.get('typologies') or [])}.",
                                             "evidence_ids": first_ev}]},
        {"heading": "Who", "sentences": [{"text": f"Subjects: {names}.", "evidence_ids": first_ev}]},
        {"heading": "What", "sentences": [{"text": f["claim"], "evidence_ids": f["evidence"]} for f in sus]},
        {"heading": "Actions taken", "sentences": [{"text": "The bank recommends filing this SAR, reviewing the relationships for exit, "
                                                            "and sharing identifiers with peer institutions under section 314(b).",
                                                    "evidence_ids": first_ev}]},
    ]
    return {"title": f"SAR draft for {case_id}", "subjects": [s["id"] for s in subjects], "typologies": case.get("typologies") or [],
            "activity_start": "", "activity_end": "", "total_suspicious_amount": 0, "sections": sections}


def _bank_name(tenant: str) -> str:
    return db.TENANT_NAMES.get(tenant, tenant)


def run_offline_sar(tenant: str, case_id: str, investigator_run: str, emit: Emit) -> dict:
    from . import agents
    writer_run = memory.start_run(tenant, case_id, "sar_writer", "template", "offline", investigator_run,
                                  "Escalated: draft the SAR narrative from the case findings and evidence.")
    emit({"type": "handoff", "from": "investigator", "to": "sar_writer", "run_id": writer_run})
    sar = offline_sar(tenant, case_id)
    emit({"type": "sar_draft", "agent": "sar_writer", "sar": sar})
    reviewer_run = memory.start_run(tenant, case_id, "reviewer", "grounding-check", "deterministic", writer_run,
                                    "Check every sentence against the cited evidence.")
    emit({"type": "handoff", "from": "sar_writer", "to": "reviewer", "run_id": reviewer_run})
    review = agents.review_sar(tenant, case_id, sar)
    emit({"type": "review", "agent": "reviewer", "review": review})
    memory.finish_run(tenant, reviewer_run, "APPROVED" if not review["issues"] else "ISSUES_REMAIN")
    memory.finish_run(tenant, writer_run, "DONE")
    sid = agents.save_sar(tenant, case_id, sar, review, writer_run, "offline")
    return {"sar_id": sid, "sar": sar, "review": review, "revisions": 0, "usage": {}}
