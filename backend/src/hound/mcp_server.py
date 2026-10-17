"""MCP server: Hound's graph tools for any MCP client (Claude Desktop, Claude Code, Cursor...).

stdio:  uv run hound mcp
HTTP:   mounted by the API at /mcp (streamable HTTP) when the web app runs.
Every call is still recorded as (:Evidence) in the bank graph, with its Cypher.
"""
from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer

from . import orchestrator, tools, triage

Tenant = Literal["alpha", "beta"]

server = MCPServer(
    name="hound",
    title="Hound AML graph tools",
    instructions="Anti-money-laundering investigation tools over FalkorDB bank graphs (synthetic data). "
                 "Start with list_alerts, then investigate an alert or call the graph tools directly. "
                 "Every result includes an evidence_id whose Cypher is stored in the graph.",
)


def _run(tenant: str, name: str, **args) -> dict:
    return tools.execute(tools.ToolContext(tenant), name, {k: v for k, v in args.items() if v is not None})


@server.tool(description="Open alerts from transaction monitoring, highest triage score first.")
def list_alerts(tenant: Tenant = "alpha", limit: int = 20) -> list[dict]:
    rows = [a for a in triage.queue(tenant) if not a.get("case_id")][:limit]
    return [{k: a[k] for k in ("id", "rule_name", "holder", "account", "party", "score", "description", "grp")} for a in rows]


@server.tool(description="Run the full Hound agent pipeline on an alert (triage, investigator, SAR writer, reviewer) "
                         "and return the case with findings and SAR.")
def investigate_alert(alert_id: str, tenant: Tenant = "alpha", mode: Literal["auto", "offline"] = "auto") -> dict:
    out = orchestrator.investigate(tenant, alert_id, lambda e: None, mode=mode)
    detail = orchestrator.case_detail(tenant, out["case_id"])
    return {"case": detail["case"], "findings": detail["findings"], "sar": detail["sar"]}


@server.tool(description="A case with its findings, evidence (Cypher) and SAR draft.")
def get_case(case_id: str, tenant: Tenant = "alpha") -> dict:
    d = orchestrator.case_detail(tenant, case_id)
    for e in d["evidence"]:
        e.pop("graph", None)
    return d


@server.tool(description=tools.TOOLS["customer_profile"].description)
def customer_profile(entity_id: str, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "customer_profile", entity_id=entity_id)


@server.tool(description=tools.TOOLS["trace_money_flow"].description)
def trace_money_flow(account_id: str, direction: Literal["out", "in"] = "out", max_hops: int = 4,
                     window_hours: int = 72, min_amount: float = 1000, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "trace_money_flow", account_id=account_id, direction=direction, max_hops=max_hops,
                window_hours=window_hours, min_amount=min_amount)


@server.tool(description=tools.TOOLS["identity_cluster"].description)
def identity_cluster(party_id: str, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "identity_cluster", party_id=party_id)


@server.tool(description=tools.TOOLS["sanctions_exposure"].description)
def sanctions_exposure(entity_id: str, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "sanctions_exposure", entity_id=entity_id)


@server.tool(description=tools.TOOLS["find_cycles"].description)
def find_cycles(account_id: str, max_length: int = 5, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "find_cycles", account_id=account_id, max_length=max_length)


@server.tool(description=tools.TOOLS["cash_structuring_profile"].description)
def cash_structuring_profile(account_id: str, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "cash_structuring_profile", account_id=account_id)


@server.tool(description=tools.TOOLS["consortium_check"].description)
def consortium_check(party_id: str, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "consortium_check", party_id=party_id)


@server.tool(description=tools.TOOLS["recall_memory"].description)
def recall_memory(entity_ids: list[str], typology: str | None = None, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "recall_memory", entity_ids=entity_ids, typology=typology)


@server.tool(description=tools.TOOLS["run_cypher"].description)
def run_cypher(query: str, purpose: str, tenant: Tenant = "alpha") -> dict:
    return _run(tenant, "run_cypher", query=query, purpose=purpose)


def main() -> None:
    server.run("stdio")
