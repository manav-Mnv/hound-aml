"""Exercise the Claude investigator loop and SAR pipeline against a scripted fake API.

Needs a seeded FalkorDB (uv run hound seed). Run: uv run python -m pytest tests -q
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

from hound import agents, evaluate, memory, orchestrator, triage
from hound.config import settings


def _resp(blocks, stop="tool_use"):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=800))


def _tool(i, name, args):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input=args)


def test_llm_pipeline(monkeypatch):
    tenant = "alpha"
    evaluate.reset_investigations(tenant)
    top = triage.score_alerts(tenant)[0]
    calls = {"n": 0}
    evidence_seen: list[str] = []

    def fake_call(system, messages, *, tools_list=None, fmt=None, effort=None, max_tokens=16000):
        calls["n"] += 1
        if fmt:  # SAR writer
            dossier = agents.case_dossier(tenant, case_id_holder["id"])
            ev = [e["id"] for e in dossier["evidence"]]
            first = dossier["findings"][0]
            sar = {"title": "Mule ring", "subjects": ["x"], "typologies": ["MONEY_MULE"], "activity_start": "",
                   "activity_end": "", "total_suspicious_amount": 0,
                   "sections": [{"heading": "What", "sentences": [{"text": first["claim"], "evidence_ids": first["evidence"]},
                                                                  {"text": "An invented $999,999 transfer.", "evidence_ids": ev[:1]}]}]}
            if any("failed the grounding review" in m["content"] for m in messages if isinstance(m["content"], str)):
                sar["sections"][0]["sentences"] = sar["sections"][0]["sentences"][:1]
            return _resp([NS(type="thinking", thinking="drafting"), NS(type="text", text=json.dumps(sar))], "end_turn")
        last = messages[-1]["content"]
        if calls["n"] == 1:
            return _resp([NS(type="thinking", thinking="Start with memory."),
                          _tool(1, "recall_memory", {"entity_ids": [top["party"], top["account"]]}),
                          _tool(2, "identity_cluster", {"party_id": top["party"]})])
        if calls["n"] == 2:
            for block in last:
                payload = json.loads(block["content"])
                if payload.get("evidence_id"):
                    evidence_seen.append(payload["evidence_id"])
            return _resp([_tool(3, "record_finding", {"typology": "MONEY_MULE", "claim": "Identity cluster of new accounts.",
                                                      "severity": "high", "confidence": 0.9, "evidence_ids": evidence_seen[-1:]}),
                          _tool(4, "submit_disposition", {"disposition": "ESCALATE_SAR", "typologies": ["MONEY_MULE"],
                                                          "risk_score": 90, "rationale": f"See {evidence_seen[-1]}",
                                                          "recommended_actions": ["File SAR"]})])
        raise AssertionError("loop should have stopped after submit_disposition")

    case_id_holder = {}
    monkeypatch.setattr(agents, "call_claude", fake_call)
    monkeypatch.setattr(type(settings), "has_llm", property(lambda self: True))
    events = []

    def emit(e):
        events.append(e)
        if e["type"] == "case_opened":
            case_id_holder["id"] = e["case_id"]

    out = orchestrator.investigate(tenant, top["alert"], emit)
    detail = orchestrator.case_detail(tenant, out["case_id"])
    assert detail["case"]["disposition"] == "SAR_RECOMMENDED"
    assert len(detail["findings"]) == 1
    assert out["sar"]["revisions"] == 1                       # reviewer caught the invented amount
    assert out["sar"]["review"]["issues"] == []                # and the revision fixed it
    agents_run = [r["agent"] for r in detail["runs"]]
    assert agents_run == ["triage", "investigator", "sar_writer", "reviewer"]
    assert any(e["type"] == "thinking" for e in events)
    assert memory.recall(tenant, [top["account"]])["direct_cases"]
