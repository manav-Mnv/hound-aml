"""Benchmark: rules-only alert queue vs. Hound, scored against the planted ground truth.

Ground truth lives in data/ground_truth.json and is never written to the graph, so agents
cannot see it. Run with:  uv run hound eval --mode offline
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import db, orchestrator, triage

DATA = Path(__file__).resolve().parents[2] / "data"


def reset_investigations(tenant: str) -> None:
    g = db.graph(tenant)
    g.query("""MATCH (c:Case {origin: 'hound'})
               OPTIONAL MATCH (c)-[:HAS_FINDING]->(f:Finding)
               OPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(e:Evidence)
               OPTIONAL MATCH (r:AgentRun)-[:WORKED_ON]->(c)
               OPTIONAL MATCH (s:SAR)-[:FOR_CASE]->(c)
               OPTIONAL MATCH (l:Lesson)-[:LEARNED_FROM]->(c)
               DETACH DELETE f, e, r, s, l, c""")
    g.query("MATCH (l:Lesson {author: 'hound-agent'}) DETACH DELETE l")
    g.query("MATCH (al:Alert) SET al.status = 'NEW'")


def run(tenant: str = "alpha", mode: str = "offline", limit: int | None = None, verbose: bool = True) -> dict:
    truth = json.loads((DATA / "ground_truth.json").read_text())[tenant]
    bad_accounts = {a: k for k, s in truth.items() for a in s["accounts"]}
    reset_investigations(tenant)
    started = time.time()
    scored = triage.score_alerts(tenant)
    triage_ms = (time.time() - started) * 1000
    worked = 0
    for s in scored:
        if limit and worked >= limit:
            break
        current = {a["id"]: a for a in triage.queue(tenant)}[s["alert"]]
        if current.get("case_id"):
            continue
        orchestrator.investigate(tenant, s["alert"], lambda e: None, mode=mode)
        worked += 1
        if verbose:
            print(f"  investigated {s['alert']} ({s['name']}) score {s['score']}")
    elapsed = time.time() - started

    alerts = triage.queue(tenant)
    cases = orchestrator.list_cases(tenant)
    hound_cases = [c for c in cases if c["origin"] == "hound"]
    g = db.graph(tenant)
    case_accounts, _ = db.rows(g, """MATCH (c:Case {origin: 'hound'})-[:CONCERNS]->(a:Account)
                                     RETURN c.id AS case_id, c.disposition AS disposition, collect(a.id) AS accounts""")
    escalated = {"SAR_RECOMMENDED", "MONITOR_EDD", "SAR_FILED"}
    tp = fp = fn = tn = 0
    for a in alerts:
        is_bad = a["account"] in bad_accounts
        flagged = a.get("disposition") in escalated
        tp += is_bad and flagged
        fp += (not is_bad) and flagged
        fn += is_bad and not flagged
        tn += (not is_bad) and not flagged
    sar_cases = [c for c in case_accounts if c["disposition"] == "SAR_RECOMMENDED"]
    covered = {}
    for key, sc in truth.items():
        hit = [c for c in sar_cases if set(c["accounts"]) & set(sc["accounts"])]
        found = set().union(*[set(c["accounts"]) for c in hit]) & set(sc["accounts"]) if hit else set()
        covered[key] = {"title": sc["title"], "detected": bool(hit), "cases": [c["case_id"] for c in hit],
                        "accounts_found": len(found), "accounts_total": len(sc["accounts"])}
    alerted = {a["account"] for a in alerts}
    discovered = {acc for c in sar_cases for acc in c["accounts"] if acc in bad_accounts and acc not in alerted}
    false_sar_cases = [c["case_id"] for c in sar_cases if not set(c["accounts"]) & set(bad_accounts)]
    n_alerts = len(alerts)
    true_alerts = sum(1 for a in alerts if a["account"] in bad_accounts)
    result = {
        "tenant": tenant, "mode": mode, "seconds": round(elapsed, 1), "triage_ms": round(triage_ms),
        "alerts": n_alerts, "true_alerts": true_alerts,
        "rules_only": {"alerts_to_review": n_alerts, "precision": round(true_alerts / n_alerts, 3)},
        "hound": {
            "cases_opened": len(hound_cases), "investigations_run": worked,
            "alerts_merged_into_cases": sum(c["alerts"] for c in hound_cases) - len(hound_cases),
            "sar_recommended_cases": len(sar_cases), "false_sar_cases": false_sar_cases,
            "alert_precision": round(tp / (tp + fp), 3) if tp + fp else 0.0,
            "alert_recall": round(tp / (tp + fn), 3) if tp + fn else 0.0,
            "false_positive_alerts_closed": tn, "false_positive_alerts_total": n_alerts - true_alerts,
            "accounts_found_without_alerts": sorted(discovered),
        },
        "scenarios": covered,
    }
    (DATA / f"eval_{tenant}_{mode}.json").write_text(json.dumps(result, indent=2))
    return result
