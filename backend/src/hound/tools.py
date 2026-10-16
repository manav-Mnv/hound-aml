"""Investigation tools. Every tool is a Cypher query (or a FalkorDB algorithm) over the bank graph.

Each call is persisted as an (:Evidence) node holding the exact Cypher and parameters, linked to
the entities it touched. Findings and SAR sentences must cite those evidence ids, which is how
every conclusion stays traceable back to the query that produced it.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Callable

from . import consortium, db, memory
from .world.generator import JURISDICTIONS, SIM_END

READ_ONLY_MAX_ROWS = 50
HIGH_RISK_CODES = {c for c, j in JURISDICTIONS.items() if j["risk"] == "high"}


def fmt_ts(ts: int | float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def money(x: float | None) -> str:
    return f"${(x or 0):,.0f}"


# ============================================================================ plumbing

@dataclass
class Viz:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[str, dict] = field(default_factory=dict)

    def node(self, nid: str, kind: str, label: str | None = None, **props) -> None:
        if not nid:
            return
        cur = self.nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label or nid})
        if label:
            cur["label"] = label
        cur.update({k: v for k, v in props.items() if v is not None})

    def edge(self, src: str, dst: str, rel: str, key: str | None = None, **props) -> None:
        eid = key or f"{src}|{rel}|{dst}"
        cur = self.edges.setdefault(eid, {"id": eid, "source": src, "target": dst, "rel": rel})
        cur.update({k: v for k, v in props.items() if v is not None})

    def to_dict(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values())}


@dataclass
class ToolResult:
    summary: str
    data: Any
    queries: list[tuple[str, dict]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    viz: Viz = field(default_factory=Viz)
    ms: float = 0.0


@dataclass
class ToolContext:
    tenant: str
    case_id: str | None = None
    run_id: str | None = None
    emit: Callable[[dict], None] = lambda e: None


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict
    fn: Callable[..., Any]
    kind: str = "read"     # read | write

    def anthropic(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


TOOLS: dict[str, ToolSpec] = {}


def tool(name: str, description: str, properties: dict, required: list[str], kind: str = "read"):
    schema = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}

    def deco(fn):
        TOOLS[name] = ToolSpec(name, description, schema, fn, kind)
        return fn
    return deco


class Q:
    """Collects the Cypher a tool runs so it can be stored as evidence."""

    def __init__(self, tenant: str):
        self.g = db.graph(tenant)
        self.log: list[tuple[str, dict]] = []
        self.ms = 0.0

    def __call__(self, cypher: str, params: dict | None = None) -> list[dict]:
        out, ms = db.rows(self.g, cypher, params or {})
        self.log.append((cypher.strip(), params or {}))
        self.ms += ms
        return out


def execute(ctx: ToolContext, name: str, args: dict) -> dict:
    """Run a tool, persist evidence, stream a UI event, and return the LLM-facing payload."""
    spec = TOOLS.get(name)
    if spec is None:
        return {"error": f"unknown tool {name}"}
    missing = [r for r in spec.schema.get("required", []) if r not in args]
    if missing:
        return {"error": f"missing arguments: {missing}"}
    allowed = set(spec.schema["properties"])
    args = {k: v for k, v in args.items() if k in allowed}
    ctx.emit({"type": "tool_call", "tool": name, "args": args})
    try:
        result = spec.fn(ctx, **args)
    except Exception as exc:  # surfaced to the model as a tool error, never swallowed silently
        ctx.emit({"type": "tool_error", "tool": name, "error": str(exc)})
        return {"error": f"{type(exc).__name__}: {exc}"}
    if spec.kind == "write":
        ctx.emit({"type": "action", "tool": name, "result": result})
        return result
    cypher = "\n\n".join(q for q, _ in result.queries)
    params = [p for _, p in result.queries]
    evidence_id = memory.record_evidence(ctx.tenant, ctx.case_id, ctx.run_id, name, cypher, params,
                                         result.summary, result.entities, _count(result.data), result.ms)
    ctx.emit({"type": "evidence", "tool": name, "evidence_id": evidence_id, "summary": result.summary,
              "cypher": [q for q, _ in result.queries], "params": params, "ms": round(result.ms, 1),
              "graph": result.viz.to_dict(), "data": _truncate(result.data, 40)})
    return {"evidence_id": evidence_id, "summary": result.summary, "data": _truncate(result.data, 25)}


def _count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return sum(len(v) for v in data.values() if isinstance(v, list)) or 1
    return 1


def _truncate(data: Any, n: int) -> Any:
    if isinstance(data, list):
        return data[:n] + ([f"... {len(data) - n} more"] if len(data) > n else [])
    if isinstance(data, dict):
        return {k: _truncate(v, n) for k, v in data.items()}
    return data


def _resolve_account(q: Q, ref: str) -> dict:
    found = q("""OPTIONAL MATCH (a:Account {id: $ref})
                 OPTIONAL MATCH (p:Party {id: $ref})-[:HOLDS]->(pa:Account)
                 WITH coalesce(a, pa) AS acc WHERE acc IS NOT NULL
                 MATCH (h:Party)-[:HOLDS]->(acc)
                 RETURN acc.id AS account, h.id AS party, h.name AS name LIMIT 1""", {"ref": ref})
    if not found:
        raise ValueError(f"no account or party with id {ref}")
    return found[0]


def _resolve_party(q: Q, ref: str) -> dict:
    found = q("""OPTIONAL MATCH (p:Party {id: $ref})
                 OPTIONAL MATCH (h:Party)-[:HOLDS]->(:Account {id: $ref})
                 WITH coalesce(p, h) AS party WHERE party IS NOT NULL
                 RETURN party.id AS party, party.name AS name, labels(party) AS labels LIMIT 1""", {"ref": ref})
    if not found:
        raise ValueError(f"no party or account with id {ref}")
    return found[0]


def _kind(labels: list[str]) -> str:
    for k in ("Sanctioned", "External", "Company", "Person", "Account", "Device", "IP", "Phone", "Email",
              "Address", "Branch"):
        if k in labels:
            return k
    return labels[0] if labels else "Node"


# ============================================================================ context tools

@tool("get_alert", "Fetch a transaction-monitoring alert with the flagged account, its holder and the rule that fired.",
      {"alert_id": {"type": "string", "description": "Alert id, e.g. ALR-R4-300123"}}, ["alert_id"])
def get_alert(ctx: ToolContext, alert_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    rows = q("""MATCH (al:Alert {id: $id})-[:ON]->(a:Account)<-[:HOLDS]-(h:Party)
                OPTIONAL MATCH (other:Alert)-[:ON]->(a) WHERE other.id <> al.id
                RETURN al.id AS alert, al.rule AS rule, al.rule_name AS rule_name, al.typology AS typology,
                       al.description AS description, al.status AS status, a.id AS account, a.opened AS opened,
                       h.id AS party, h.name AS holder, labels(h) AS labels,
                       collect(other.rule_name) AS other_alerts_same_account""", {"id": alert_id})
    if not rows:
        raise ValueError(f"alert {alert_id} not found")
    r = rows[0]
    r["opened"] = fmt_ts(r["opened"])
    v = Viz()
    v.node(r["party"], _kind(r["labels"]), r["holder"], focus=True)
    v.node(r["account"], "Account", r["account"], alert=True)
    v.edge(r["party"], r["account"], "HOLDS")
    return ToolResult(f"{r['rule_name']} on {r['account']} held by {r['holder']}: {r['description']}",
                      r, q.log, [r["party"], r["account"]], v, q.ms)


@tool("customer_profile",
      "KYC profile for a party or account: type, occupation/industry, tenure, expected activity, accounts, "
      "90-day inflow/outflow by channel, and graph scores (PageRank, betweenness, community, identity cluster).",
      {"entity_id": {"type": "string", "description": "Party id (P-/B-) or account id (AC-)"}}, ["entity_id"])
def customer_profile(ctx: ToolContext, entity_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    p = _resolve_party(q, entity_id)
    prof = q("""MATCH (p:Party {id: $id})
                OPTIONAL MATCH (p)-[:HOLDS]->(a:Account)
                WITH p, collect(a) AS accs
                RETURN p.id AS id, p.name AS name, labels(p) AS labels, p.occupation AS occupation,
                       p.industry AS industry, p.age AS age, p.country AS country, p.onboarded AS onboarded,
                       p.incorporated AS incorporated, p.risk_rating AS risk_rating,
                       p.expected_activity AS expected_activity, p.expected_monthly_inflow AS expected_monthly_inflow,
                       p.identity_cluster_size AS identity_cluster_size,
                       [a IN accs | {id: a.id, type: a.type, opened: a.opened, status: a.status,
                                     pagerank: a.pagerank, betweenness: a.betweenness, community: a.community}] AS accounts""",
              {"id": p["party"]})[0]
    flows = q("""MATCH (p:Party {id: $id})-[:HOLDS]->(a:Account)
                 OPTIONAL MATCH (a)<-[i:TRANSFER]-()
                 WITH a, i.channel AS ch, sum(i.amount) AS amt, count(i) AS n
                 RETURN 'in' AS dir, ch AS channel, amt AS amount, n AS count
                 UNION ALL
                 MATCH (p:Party {id: $id})-[:HOLDS]->(a:Account)
                 OPTIONAL MATCH (a)-[o:TRANSFER]->()
                 WITH a, o.channel AS ch, sum(o.amount) AS amt, count(o) AS n
                 RETURN 'out' AS dir, ch AS channel, amt AS amount, n AS count
                 UNION ALL
                 MATCH (p:Party {id: $id})-[:HOLDS]->(a:Account)
                 OPTIONAL MATCH (a)<-[c:CASH_DEPOSIT]-()
                 RETURN 'in' AS dir, 'cash' AS channel, sum(c.amount) AS amount, count(c) AS count""",
             {"id": p["party"]})
    pct = q("""MATCH (p:Party {id: $id})-[:HOLDS]->(a:Account) WITH max(a.pagerank) AS pr, max(a.betweenness) AS bt
               MATCH (x:Account) WHERE NOT x:External
               RETURN pr, bt, toFloat(sum(CASE WHEN x.pagerank <= pr THEN 1 ELSE 0 END)) / count(x) AS pagerank_pct,
                      toFloat(sum(CASE WHEN x.betweenness <= bt THEN 1 ELSE 0 END)) / count(x) AS betweenness_pct""",
            {"id": p["party"]})[0]
    total_in = sum(f["amount"] or 0 for f in flows if f["dir"] == "in" and f["channel"])
    total_out = sum(f["amount"] or 0 for f in flows if f["dir"] == "out" and f["channel"])
    tenure = (SIM_END - prof["onboarded"]) // 86400 if prof.get("onboarded") else None
    prof.update({
        "type": "Company" if "Company" in prof["labels"] else "Person",
        "customer": "Customer" in prof["labels"], "sanctioned": "Sanctioned" in prof["labels"],
        "tenure_days": tenure, "onboarded": fmt_ts(prof["onboarded"]), "incorporated": fmt_ts(prof.get("incorporated")),
        "inflow_90d": round(total_in), "outflow_90d": round(total_out),
        "monthly_inflow_vs_expected": (round(total_in / 3 / prof["expected_monthly_inflow"], 2)
                                       if prof.get("expected_monthly_inflow") else None),
        "flows_by_channel": [f for f in flows if f["channel"] and f["count"]],
        "pagerank_percentile": round(pct["pagerank_pct"] or 0, 3),
        "betweenness_percentile": round(pct["betweenness_pct"] or 0, 3),
    })
    for a in prof["accounts"]:
        a["opened"] = fmt_ts(a["opened"])
    prof.pop("labels")
    v = Viz()
    v.node(prof["id"], prof["type"], prof["name"])
    for a in prof["accounts"]:
        v.node(a["id"], "Account", a["id"])
        v.edge(prof["id"], a["id"], "HOLDS")
    summary = (f"{prof['name']} ({prof['type']}, {prof.get('occupation') or prof.get('industry')}), customer for "
               f"{tenure} days; 90-day inflow {money(total_in)}, outflow {money(total_out)}")
    if prof.get("monthly_inflow_vs_expected"):
        summary += f"; inflow is {prof['monthly_inflow_vs_expected']}x expected"
    return ToolResult(summary, prof, q.log, [prof["id"]] + [a["id"] for a in prof["accounts"]], v, q.ms)


# ============================================================================ money movement

HOP_OUT = """
UNWIND $frontier AS f
MATCH (a:Account {id: f.id})-[t:TRANSFER]->(b:Account)
WHERE t.amount >= $min AND t.channel <> 'card' AND t.ts >= f.ts AND t.ts <= f.ts + f.win
RETURN f.pid AS pid, b.id AS id, b:External AS external, b.country AS country,
       head([(h:Party)-[:HOLDS]->(b) | h.name]) AS holder,
       t.amount AS amount, t.ts AS ts, t.channel AS channel, t.memo AS memo"""

HOP_IN = """
UNWIND $frontier AS f
MATCH (a:Account {id: f.id})<-[t:TRANSFER]-(b:Account)
WHERE t.amount >= $min AND t.channel <> 'card' AND t.ts <= f.ts AND t.ts >= f.ts - f.win
RETURN f.pid AS pid, b.id AS id, b:External AS external, b.country AS country,
       head([(h:Party)-[:HOLDS]->(b) | h.name]) AS holder,
       t.amount AS amount, t.ts AS ts, t.channel AS channel, t.memo AS memo"""


@tool("trace_money_flow",
      "Follow the money hop by hop through time-ordered transfers (each hop happens after the previous one, "
      "within the window). Use direction 'out' to see where funds went, 'in' to see where they came from. "
      "Keeps the largest branches at each hop so hubs do not explode.",
      {"account_id": {"type": "string"},
       "direction": {"type": "string", "enum": ["out", "in"]},
       "max_hops": {"type": "integer", "minimum": 1, "maximum": 5, "description": "default 4"},
       "window_hours": {"type": "integer", "minimum": 1, "maximum": 720, "description": "max gap between hops, default 72"},
       "min_amount": {"type": "number", "description": "ignore transfers below this, default 1000"}},
      ["account_id", "direction"])
def trace_money_flow(ctx: ToolContext, account_id: str, direction: str, max_hops: int = 4,
                     window_hours: int = 72, min_amount: float = 1000) -> ToolResult:
    q = Q(ctx.tenant)
    acc = _resolve_account(q, account_id)
    hops = max(1, min(int(max_hops), 5))
    win = int(window_hours) * 3600
    out = direction == "out"
    cypher = HOP_OUT if out else HOP_IN
    start_node = {"id": acc["account"], "holder": acc["name"], "external": False, "country": "US"}
    paths = [{"nodes": [start_node], "txs": []}]
    frontier = [{"pid": 0, "id": acc["account"], "ts": 0 if out else SIM_END + 1, "win": 10 ** 10}]
    finished, beam, cap = [], 6, 40
    for depth in range(hops):
        if not frontier:
            break
        found, ms = db.rows(q.g, cypher, {"frontier": frontier, "min": float(min_amount)})
        q.ms += ms
        if depth == 0:
            q.log.append((cypher.strip() + "\n// executed once per hop with the surviving frontier (beam search)",
                          {"start": acc["account"], "min": float(min_amount), "window_hours": window_hours, "max_hops": hops}))
        by_pid: dict[int, list[dict]] = {}
        for r in found:
            by_pid.setdefault(r["pid"], []).append(r)
        new_paths = []
        for f in frontier:
            base = paths[f["pid"]]
            seen = {n["id"] for n in base["nodes"]}
            nxt = sorted((r for r in by_pid.get(f["pid"], []) if r["id"] not in seen), key=lambda r: -r["amount"])[:beam]
            if not nxt and base["txs"]:
                finished.append(base)
            for r in nxt:
                node = {"id": r["id"], "holder": r["holder"], "external": r["external"], "country": r["country"]}
                tx = {"amount": r["amount"], "ts": r["ts"], "channel": r["channel"], "memo": r["memo"]}
                new_paths.append({"nodes": base["nodes"] + [node], "txs": base["txs"] + [tx]})
        new_paths.sort(key=lambda pth: -sum(t["amount"] for t in pth["txs"]))
        paths = new_paths[:cap]
        finished.extend(pth for pth in paths if pth["nodes"][-1]["external"])
        frontier = [{"pid": i, "id": pth["nodes"][-1]["id"], "ts": pth["txs"][-1]["ts"], "win": win}
                    for i, pth in enumerate(paths) if not pth["nodes"][-1]["external"]]
    finished.extend(pth for pth in paths if not pth["nodes"][-1]["external"])
    v = Viz()
    out_paths, endpoints, entities = [], {}, [acc["account"]]
    for pth in finished:
        nodes, txs = pth["nodes"], pth["txs"]
        for n in nodes:
            v.node(n["id"], "External" if n["external"] else "Account", n.get("holder") or n["id"],
                   country=n.get("country"), focus=n["id"] == acc["account"])
            entities.append(n["id"])
        for i, t in enumerate(txs):
            src, dst = (nodes[i]["id"], nodes[i + 1]["id"]) if out else (nodes[i + 1]["id"], nodes[i]["id"])
            v.edge(src, dst, "TRANSFER", key=f"{src}>{dst}@{t['ts']}", amount=t["amount"], ts=t["ts"], memo=t["memo"])
        end = nodes[-1]
        e = endpoints.setdefault(end["id"], {"account": end["id"], "holder": end.get("holder"), "country": end.get("country"),
                                             "external": end["external"], "paths": 0, "max_hops": 0})
        e["paths"] += 1
        e["max_hops"] = max(e["max_hops"], len(txs))
        ordered_nodes = nodes if out else list(reversed(nodes))
        ordered_txs = txs if out else list(reversed(txs))
        out_paths.append({
            "route": " -> ".join(f"{n.get('holder') or n['id']} [{n['id']}{', ' + n['country'] if n.get('country') not in (None, 'US') else ''}]"
                                 for n in ordered_nodes),
            "amounts": [round(t["amount"]) for t in ordered_txs],
            "first": fmt_ts(min(t["ts"] for t in txs)), "last": fmt_ts(max(t["ts"] for t in txs)),
            "hours_end_to_end": round((max(t["ts"] for t in txs) - min(t["ts"] for t in txs)) / 3600, 1),
            "last_to_first_ratio": round(ordered_txs[-1]["amount"] / ordered_txs[0]["amount"], 3),
            "memos": sorted({t["memo"] for t in txs if t["memo"]}),
        })
    out_paths.sort(key=lambda pth: (-len(pth["amounts"]), -sum(pth["amounts"])))
    high_risk = [e for e in endpoints.values() if e["country"] in HIGH_RISK_CODES]
    deepest = out_paths[0] if out_paths else None
    summary = (f"{len(out_paths)} time-ordered {direction}bound path(s) (>= {money(min_amount)}, hops within "
               f"{window_hours}h) from {acc['account']}")
    if deepest:
        summary += f"; deepest: {deepest['route']} ({deepest['hours_end_to_end']}h end to end)"
    if high_risk:
        summary += f"; {len(high_risk)} endpoint(s) in high-risk jurisdictions: " + ", ".join(
            f"{e['holder']} ({e['country']})" for e in high_risk[:4])
    return ToolResult(summary, {"paths": out_paths[:20], "endpoints": list(endpoints.values())[:20]}, q.log, entities, v, q.ms)


@tool("pass_through_analysis",
      "Velocity and retention: how much inbound money leaves within 24h/48h, median dwell time, and how "
      "concentrated the outbound beneficiaries are. Mule and layering accounts keep almost nothing.",
      {"account_id": {"type": "string"}}, ["account_id"])
def pass_through_analysis(ctx: ToolContext, account_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    acc = _resolve_account(q, account_id)
    rows = q("""
MATCH (src:Account)-[i:TRANSFER]->(a:Account {id: $id})
WHERE i.amount >= 500
OPTIONAL MATCH (a)-[o:TRANSFER]->(dst:Account)
WHERE o.ts >= i.ts AND o.ts <= i.ts + 172800 AND o.channel <> 'card'
WITH i, src, collect({amount: o.amount, ts: o.ts, dst: dst.id}) AS outs
RETURN i.amount AS amount, i.ts AS ts, src.id AS source, i.memo AS memo,
       reduce(s = 0.0, x IN outs | s + coalesce(x.amount, 0)) AS out48,
       reduce(s = 0.0, x IN [y IN outs WHERE y.ts <= i.ts + 86400] | s + coalesce(x.amount, 0)) AS out24,
       [x IN outs WHERE x.ts IS NOT NULL | x.ts - i.ts] AS lags,
       [x IN outs WHERE x.dst IS NOT NULL | x.dst] AS dsts
ORDER BY ts""", {"id": acc["account"]})
    beneficiaries = q("""
MATCH (a:Account {id: $id})-[o:TRANSFER]->(d:Account) WHERE o.channel <> 'card'
OPTIONAL MATCH (h:Party)-[:HOLDS]->(d)
RETURN d.id AS account, h.name AS holder, d.country AS country, sum(o.amount) AS total, count(o) AS n
ORDER BY total DESC LIMIT 8""", {"id": acc["account"]})
    inflow = sum(r["amount"] for r in rows)
    moved24 = sum(min(r["out24"], r["amount"]) for r in rows)
    moved48 = sum(min(r["out48"], r["amount"]) for r in rows)
    lags = [lag for r in rows for lag in r["lags"] if lag is not None]
    out_total = sum(b["total"] for b in beneficiaries) or 1
    data = {
        "account": acc["account"], "holder": acc["name"], "inbound_credits": len(rows), "inflow": round(inflow),
        "share_out_within_24h": round(moved24 / inflow, 3) if inflow else 0,
        "share_out_within_48h": round(moved48 / inflow, 3) if inflow else 0,
        "median_dwell_hours": round(statistics.median(lags) / 3600, 1) if lags else None,
        "top_beneficiary_share": round(beneficiaries[0]["total"] / out_total, 3) if beneficiaries else 0,
        "beneficiaries": beneficiaries,
        "sample_credits": [{"amount": round(r["amount"]), "at": fmt_ts(r["ts"]), "from": r["source"], "memo": r["memo"],
                            "out_within_48h": round(r["out48"])} for r in rows[-12:]],
    }
    v = Viz()
    v.node(acc["account"], "Account", acc["name"], focus=True)
    for r in rows[-15:]:
        v.node(r["source"], "Account", r["source"])
        v.edge(r["source"], acc["account"], "TRANSFER", key=f"{r['source']}>{acc['account']}@{r['ts']}", amount=r["amount"], ts=r["ts"])
    for b in beneficiaries:
        v.node(b["account"], "Account", b["holder"] or b["account"], country=b["country"])
        v.edge(acc["account"], b["account"], "TRANSFER", amount=b["total"], count=b["n"])
    summary = (f"{acc['account']}: {len(rows)} credits totalling {money(inflow)}; {data['share_out_within_24h']:.0%} left "
               f"within 24h and {data['share_out_within_48h']:.0%} within 48h; median dwell "
               f"{data['median_dwell_hours']}h; top beneficiary takes {data['top_beneficiary_share']:.0%} of outflow")
    if beneficiaries:
        summary += f" ({beneficiaries[0]['holder']} {beneficiaries[0]['account']})"
    ents = [acc["account"]] + [r["source"] for r in rows] + [b["account"] for b in beneficiaries]
    return ToolResult(summary, data, q.log, ents, v, q.ms)


@tool("find_cycles",
      "Search for closed loops of transfers that leave an account and come back to it (round-tripping, "
      "carousel schemes). Returns each loop with amounts, timing and the parties involved.",
      {"account_id": {"type": "string"},
       "max_length": {"type": "integer", "minimum": 2, "maximum": 6, "description": "default 5"},
       "min_amount": {"type": "number", "description": "default 5000"}},
      ["account_id"])
def find_cycles(ctx: ToolContext, account_id: str, max_length: int = 5, min_amount: float = 5000) -> ToolResult:
    q = Q(ctx.tenant)
    acc = _resolve_account(q, account_id)
    n = max(2, min(int(max_length), 6))
    rows = q(f"""
MATCH p = (a:Account {{id: $id}})-[:TRANSFER*2..{n}]->(a)
WITH p, relationships(p) AS rs
WHERE all(r IN rs WHERE r.amount >= $min)
  AND all(i IN range(0, size(rs) - 2) WHERE rs[i + 1].ts >= rs[i].ts AND rs[i + 1].ts - rs[i].ts <= 14 * 86400)
RETURN [x IN nodes(p) | {{id: x.id, holder: head([(h:Party)-[:HOLDS]->(x) | h.name])}}] AS loop,
       [r IN rs | r.amount] AS amounts, [r IN rs | r.ts] AS ts, [r IN rs | r.memo] AS memos
ORDER BY ts[0] LIMIT 25""", {"id": acc["account"], "min": float(min_amount)})
    v = Viz()
    loops, ents = [], [acc["account"]]
    for r in rows:
        ids = [x["id"] for x in r["loop"]]
        for x in r["loop"]:
            v.node(x["id"], "Account", x["holder"] or x["id"], focus=x["id"] == acc["account"])
            ents.append(x["id"])
        for i, amt in enumerate(r["amounts"]):
            v.edge(ids[i], ids[i + 1], "TRANSFER", key=f"{ids[i]}>{ids[i+1]}@{r['ts'][i]}", amount=amt, ts=r["ts"][i])
        loops.append({"route": " -> ".join(x["holder"] or x["id"] for x in r["loop"]),
                      "amounts": [round(a) for a in r["amounts"]],
                      "started": fmt_ts(r["ts"][0]), "days_to_close": round((r["ts"][-1] - r["ts"][0]) / 86400, 1),
                      "value_returned": round(r["amounts"][-1] / r["amounts"][0], 3), "memos": sorted(set(r["memos"]))})
    summary = (f"{len(loops)} closed loop(s) through {acc['account']}" +
               (f"; e.g. {loops[0]['route']} closing in {loops[0]['days_to_close']} days with "
                f"{loops[0]['value_returned']:.0%} of value returned" if loops else "; no round-tripping found"))
    return ToolResult(summary, {"cycles": loops}, q.log, ents, v, q.ms)


@tool("counterparty_summary",
      "Top counterparties in and out of an account, with totals, counts, channels, jurisdictions, counterparty "
      "type and sample memos. Use to judge whether flows fit the customer's business.",
      {"account_id": {"type": "string"}}, ["account_id"])
def counterparty_summary(ctx: ToolContext, account_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    acc = _resolve_account(q, account_id)
    rows = q("""
MATCH (a:Account {id: $id})-[t:TRANSFER]-(x:Account)
WHERE t.channel <> 'card'
WITH x, CASE WHEN startNode(t) = a THEN 'out' ELSE 'in' END AS dir, count(t) AS n, sum(t.amount) AS total,
     collect(t.channel) AS channels, collect(t.memo) AS memos
OPTIONAL MATCH (h:Party)-[:HOLDS]->(x)
RETURN dir, x.id AS account, h.id AS party, h.name AS name, coalesce(h.industry, h.occupation) AS business,
       x.country AS country, x:External AS external, n, total, channels, memos, h.onboarded AS onboarded
ORDER BY total DESC LIMIT 30""", {"id": acc["account"]})
    v = Viz()
    v.node(acc["account"], "Account", acc["name"], focus=True)
    for r in rows:
        r["total"] = round(r["total"])
        r["memos"] = sorted({m for m in r["memos"] if m})[:3]
        r["channels"] = sorted(set(r["channels"]))
        r["counterparty_tenure_days"] = (SIM_END - r.pop("onboarded")) // 86400 if r.get("onboarded") else None
        v.node(r["account"], "External" if r["external"] else "Account", r["name"] or r["account"], country=r["country"])
        src, dst = (acc["account"], r["account"]) if r["dir"] == "out" else (r["account"], acc["account"])
        v.edge(src, dst, "TRANSFER", amount=r["total"], count=r["n"])
    ins = [r for r in rows if r["dir"] == "in"]
    outs = [r for r in rows if r["dir"] == "out"]
    hr = [r for r in rows if r["country"] in {c for c, j in JURISDICTIONS.items() if j["risk"] == "high"}]
    summary = (f"{len(ins)} inbound and {len(outs)} outbound counterparties for {acc['account']}"
               + (f"; largest source {ins[0]['name']} {money(ins[0]['total'])}" if ins else "")
               + (f"; largest beneficiary {outs[0]['name']} {money(outs[0]['total'])}" if outs else "")
               + (f"; high-risk jurisdictions: {', '.join(sorted({r['country'] for r in hr}))}" if hr else ""))
    return ToolResult(summary, {"inbound": ins, "outbound": outs}, q.log,
                      [acc["account"]] + [r["account"] for r in rows] + [r["party"] for r in rows if r["party"]], v, q.ms)


@tool("cash_structuring_profile",
      "Profile cash deposits into an account: amount bands relative to the $10,000 CTR threshold, CTR-filed "
      "deposits, branches and days used, and linked depositors - other customers who deposit cash and forward "
      "it to this account within 48 hours (smurfs).",
      {"account_id": {"type": "string"}}, ["account_id"])
def cash_structuring_profile(ctx: ToolContext, account_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    acc = _resolve_account(q, account_id)
    deps = q("""MATCH (b:Branch)-[c:CASH_DEPOSIT]->(a:Account {id: $id})
                RETURN c.amount AS amount, c.ts AS ts, c.ctr AS ctr, b.id AS branch, b.city AS city ORDER BY ts""",
             {"id": acc["account"]})
    smurfs = q("""
MATCH (b:Branch)-[c:CASH_DEPOSIT]->(sa:Account)-[t:TRANSFER]->(a:Account {id: $id})
WHERE t.ts >= c.ts AND t.ts - c.ts <= 172800 AND t.amount >= 0.8 * c.amount AND sa.id <> a.id
MATCH (s:Party)-[:HOLDS]->(sa)
RETURN s.id AS party, s.name AS name, s.age AS age, s.occupation AS occupation, sa.id AS account,
       count(c) AS deposits, sum(c.amount) AS cash_in, sum(t.amount) AS forwarded,
       collect(DISTINCT b.id) AS branches, min(c.amount) AS min_dep, max(c.amount) AS max_dep
ORDER BY forwarded DESC""", {"id": acc["account"]})
    bands = {"under_3k": 0, "3k_8k": 0, "8k_10k": 0, "over_10k_ctr": 0}
    for d in deps:
        a = d["amount"]
        key = "under_3k" if a < 3000 else "3k_8k" if a < 8000 else "8k_10k" if a < 10000 else "over_10k_ctr"
        bands[key] += 1
    n = len(deps) or 1
    data = {
        "account": acc["account"], "holder": acc["name"], "deposits": len(deps),
        "total_cash": round(sum(d["amount"] for d in deps)), "bands": bands,
        "share_in_8k_10k_band": round(bands["8k_10k"] / n, 3), "ctr_filed_deposits": bands["over_10k_ctr"],
        "branches_used": sorted({d["branch"] for d in deps}),
        "linked_depositors": [{**s, "cash_in": round(s["cash_in"]), "forwarded": round(s["forwarded"])} for s in smurfs],
        "recent_deposits": [{"amount": round(d["amount"]), "at": fmt_ts(d["ts"]), "branch": d["branch"]} for d in deps[-10:]],
    }
    v = Viz()
    v.node(acc["account"], "Account", acc["name"], focus=True)
    for d in deps[-12:]:
        v.node(d["branch"], "Branch", f"{d['branch']} {d['city']}")
        v.edge(d["branch"], acc["account"], "CASH_DEPOSIT", key=f"{d['branch']}>{acc['account']}@{d['ts']}", amount=d["amount"], ts=d["ts"])
    for s in smurfs:
        v.node(s["party"], "Person", s["name"])
        v.node(s["account"], "Account", s["name"])
        v.edge(s["party"], s["account"], "HOLDS")
        v.edge(s["account"], acc["account"], "TRANSFER", amount=s["forwarded"], count=s["deposits"])
        for b in s["branches"]:
            v.node(b, "Branch", b)
            v.edge(b, s["account"], "CASH_DEPOSIT", amount=s["cash_in"])
    summary = (f"{len(deps)} cash deposits into {acc['account']} ({money(data['total_cash'])}); "
               f"{bands['8k_10k']} in the $8k-$10k band vs {bands['over_10k_ctr']} above $10k (CTR filed); "
               f"{len(data['branches_used'])} branches")
    if smurfs:
        summary += (f"; {len(smurfs)} linked depositor(s) deposited {money(sum(s['cash_in'] for s in smurfs))} cash "
                    f"and forwarded {money(sum(s['forwarded'] for s in smurfs))} here within 48h")
    ents = [acc["account"]] + [s["party"] for s in smurfs] + [s["account"] for s in smurfs]
    return ToolResult(summary, data, q.log, ents, v, q.ms)


# ============================================================================ identity & networks

IDENTITY_LABELS = ["Person", "Company", "Device", "IP", "Phone"]
IDENTITY_RELS = ["USES", "LOGGED_IN_FROM", "HAS_PHONE"]


@tool("identity_cluster",
      "Run FalkorDB's WCC algorithm over the identity graph (parties linked through shared devices, IPs and "
      "phones) and return the connected cluster containing this party: members, what links them, account ages "
      "and alert counts. Rings operated by the same people show up as one cluster.",
      {"party_id": {"type": "string", "description": "Party id or account id"}}, ["party_id"])
def identity_cluster(ctx: ToolContext, party_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    p = _resolve_party(q, party_id)
    rows = q("""
CALL algo.WCC({nodeLabels: $labels, relationshipTypes: $rels}) YIELD node, componentId
WITH componentId, collect(node) AS members
WHERE any(m IN members WHERE m.id = $id)
UNWIND members AS m
WITH m WHERE m:Party
OPTIONAL MATCH (m)-[:HOLDS]->(a:Account)
OPTIONAL MATCH (al:Alert)-[:ON]->(a)
RETURN m.id AS party, m.name AS name, m.age AS age, m.occupation AS occupation, m.onboarded AS onboarded,
       collect(DISTINCT a.id) AS accounts, count(DISTINCT al) AS alerts""",
             {"labels": IDENTITY_LABELS, "rels": IDENTITY_RELS, "id": p["party"]})
    members = [r["party"] for r in rows]
    links = q("""
UNWIND $ids AS pid
MATCH (x:Party {id: pid})-[r:USES|LOGGED_IN_FROM|HAS_PHONE]->(i)<-[:USES|LOGGED_IN_FROM|HAS_PHONE]-(y:Party)
WHERE y.id IN $ids AND x.id < y.id
RETURN x.id AS a, y.id AS b, labels(i)[0] AS via, i.id AS identifier,
       coalesce(i.fingerprint, i.addr, i.number, i.id) AS value""", {"ids": members})
    for r in rows:
        r["tenure_days"] = (SIM_END - r.pop("onboarded")) // 86400 if r.get("onboarded") else None
    v = Viz()
    for r in rows:
        v.node(r["party"], "Person", r["name"], focus=r["party"] == p["party"], alerts=r["alerts"])
    for l in links:
        v.node(l["identifier"], l["via"], l["value"])
        v.edge(l["a"], l["identifier"], {"Device": "USES", "IP": "LOGGED_IN_FROM", "Phone": "HAS_PHONE"}[l["via"]])
        v.edge(l["b"], l["identifier"], {"Device": "USES", "IP": "LOGGED_IN_FROM", "Phone": "HAS_PHONE"}[l["via"]])
    new = [r for r in rows if r["tenure_days"] is not None and r["tenure_days"] <= 90]
    shared = sorted({(l["via"], l["value"]) for l in links})
    summary = (f"WCC identity cluster of {p['name']} has {len(rows)} part(ies); {len(new)} onboarded in the last 90 days; "
               f"{sum(r['alerts'] for r in rows)} alert(s) across members; shared identifiers: "
               + (", ".join(f"{k} {v}" for k, v in shared[:6]) if shared else "none"))
    data = {"members": rows, "shared_identifiers": [{"type": k, "value": val} for k, val in shared], "links": links[:40]}
    return ToolResult(summary, data, q.log, members + [a for r in rows for a in r["accounts"]], v, q.ms)


@tool("shared_identifiers",
      "Direct identifier overlap: other parties who share this party's devices, IPs, phones, e-mails or "
      "addresses, with their tenure and alert counts.",
      {"party_id": {"type": "string"}}, ["party_id"])
def shared_identifiers(ctx: ToolContext, party_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    p = _resolve_party(q, party_id)
    rows = q("""
MATCH (p:Party {id: $id})-[r:USES|LOGGED_IN_FROM|HAS_PHONE|HAS_EMAIL|LIVES_AT|REGISTERED_AT]->(i)<-[:USES|LOGGED_IN_FROM|HAS_PHONE|HAS_EMAIL|LIVES_AT|REGISTERED_AT]-(o:Party)
WHERE o.id <> p.id
OPTIONAL MATCH (o)-[:HOLDS]->(:Account)<-[:ON]-(al:Alert)
RETURN o.id AS party, o.name AS name, o.onboarded AS onboarded, labels(i)[0] AS via, i.id AS identifier,
       coalesce(i.fingerprint, i.addr, i.number, i.line, i.id) AS value, count(DISTINCT al) AS alerts""",
             {"id": p["party"]})
    v = Viz()
    v.node(p["party"], "Person", p["name"], focus=True)
    for r in rows:
        r["tenure_days"] = (SIM_END - r.pop("onboarded")) // 86400 if r.get("onboarded") else None
        v.node(r["party"], "Person", r["name"], alerts=r["alerts"])
        v.node(r["identifier"], r["via"], r["value"])
        v.edge(p["party"], r["identifier"], "SHARES")
        v.edge(r["party"], r["identifier"], "SHARES")
    surnames = {p["name"].split()[-1]} if p.get("name") else set()
    same_family = [r for r in rows if r["name"] and r["name"].split()[-1] in surnames]
    summary = (f"{p['name']} shares identifiers with {len({r['party'] for r in rows})} other part(ies)"
               + (f" via {', '.join(sorted({r['via'] for r in rows}))}" if rows else "")
               + (f"; {len({r['party'] for r in same_family})} share the same surname (possible household)" if same_family else ""))
    return ToolResult(summary, {"overlaps": rows}, q.log, [p["party"]] + [r["party"] for r in rows], v, q.ms)


@tool("corporate_network",
      "Corporate registry view of a company (or a person's companies): owners with percentages, directors, "
      "registered address, and sibling companies sharing a director, owner or address, with incorporation dates.",
      {"party_id": {"type": "string", "description": "Company or person id, or an account id"}}, ["party_id"])
def corporate_network(ctx: ToolContext, party_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    p = _resolve_party(q, party_id)
    core = q("""
MATCH (c:Party {id: $id})
OPTIONAL MATCH (o:Party)-[ow:OWNS]->(c)
OPTIONAL MATCH (d:Party)-[:DIRECTOR_OF]->(c)
OPTIONAL MATCH (c)-[:REGISTERED_AT]->(addr:Address)
RETURN c.id AS id, c.name AS name, c.country AS country, c.incorporated AS incorporated,
       collect(DISTINCT {id: o.id, name: o.name, pct: ow.pct, sanctioned: o:Sanctioned}) AS owners,
       collect(DISTINCT {id: d.id, name: d.name}) AS directors,
       collect(DISTINCT {id: addr.id, line: addr.line, city: addr.city, country: addr.country}) AS addresses""",
             {"id": p["party"]})[0]
    siblings = q("""
MATCH (c:Party {id: $id})
MATCH (c)<-[:DIRECTOR_OF|OWNS]-(k:Party)-[:DIRECTOR_OF|OWNS]->(s:Company)
WHERE s.id <> c.id
RETURN DISTINCT s.id AS id, s.name AS name, s.incorporated AS incorporated, s.country AS country,
       'shared officer/owner ' + k.name AS link, s:Customer AS customer
UNION
MATCH (c:Party {id: $id})-[:REGISTERED_AT]->(a:Address)<-[:REGISTERED_AT]-(s:Company)
WHERE s.id <> c.id
RETURN DISTINCT s.id AS id, s.name AS name, s.incorporated AS incorporated, s.country AS country,
       'same registered address ' + a.line AS link, s:Customer AS customer""", {"id": p["party"]})
    owned = q("""MATCH (c:Party {id: $id})-[ow:OWNS|DIRECTOR_OF]->(s:Company)
                 RETURN s.id AS id, s.name AS name, type(ow) AS rel, ow.pct AS pct, s.incorporated AS incorporated""",
              {"id": p["party"]})
    merged: dict[str, dict] = {}
    for sib in siblings:
        cur = merged.setdefault(sib["id"], {**{k: v for k, v in sib.items() if k != "link"}, "links": []})
        cur["links"].append(sib["link"])
    siblings = list(merged.values())
    core["owners"] = [o for o in core["owners"] if o.get("id")]
    core["directors"] = [d for d in core["directors"] if d.get("id")]
    core["addresses"] = [a for a in core["addresses"] if a.get("id")]
    core["incorporated"] = fmt_ts(core["incorporated"])
    for s in siblings + owned:
        s["incorporated"] = fmt_ts(s.get("incorporated"))
    v = Viz()
    v.node(core["id"], "Company", core["name"], focus=True)
    for o in core["owners"]:
        v.node(o["id"], "Sanctioned" if o["sanctioned"] else "Person", o["name"])
        v.edge(o["id"], core["id"], "OWNS", pct=o["pct"])
    for d in core["directors"]:
        v.node(d["id"], "Person", d["name"])
        v.edge(d["id"], core["id"], "DIRECTOR_OF")
    for a in core["addresses"]:
        v.node(a["id"], "Address", a["line"])
        v.edge(core["id"], a["id"], "REGISTERED_AT")
    for s in siblings:
        v.node(s["id"], "Company", s["name"])
        v.edge(core["id"], s["id"], "RELATED", label="; ".join(s["links"]))
    for s in owned:
        v.node(s["id"], "Company", s["name"])
        v.edge(core["id"], s["id"], s["rel"], pct=s["pct"])
    inc_dates = [s["incorporated"] for s in siblings if s["incorporated"]]
    summary = (f"{core['name']}: {len(core['owners'])} owner(s), {len(core['directors'])} director(s); "
               f"{len(siblings)} sibling compan(ies) linked by officer/owner/address"
               + (f" (incorporated {min(inc_dates)} to {max(inc_dates)})" if inc_dates else "")
               + (f"; controls {len(owned)} compan(ies)" if owned else ""))
    ents = [core["id"]] + [o["id"] for o in core["owners"]] + [d["id"] for d in core["directors"]] + [s["id"] for s in siblings + owned]
    return ToolResult(summary, {"company": core, "siblings": siblings, "controls": owned}, q.log, ents, v, q.ms)


@tool("network_position",
      "Where an account sits in the transfer network, from FalkorDB algorithms: PageRank and betweenness "
      "percentiles (collectors and brokers score high) and its label-propagation community, with other alerted "
      "accounts in that community.",
      {"account_id": {"type": "string"}}, ["account_id"])
def network_position(ctx: ToolContext, account_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    acc = _resolve_account(q, account_id)
    rows = q("""
MATCH (a:Account {id: $id})
MATCH (x:Account) WHERE NOT x:External
WITH a, toFloat(sum(CASE WHEN x.pagerank <= a.pagerank THEN 1 ELSE 0 END)) / count(x) AS pr_pct,
        toFloat(sum(CASE WHEN x.betweenness <= a.betweenness THEN 1 ELSE 0 END)) / count(x) AS bt_pct
MATCH (m:Account) WHERE m.community = a.community
OPTIONAL MATCH (al:Alert)-[:ON]->(m)
OPTIONAL MATCH (h:Party)-[:HOLDS]->(m)
RETURN a.pagerank AS pagerank, a.betweenness AS betweenness, pr_pct, bt_pct, a.community AS community,
       count(DISTINCT m) AS community_size,
       collect(DISTINCT CASE WHEN al IS NOT NULL AND m.id <> a.id THEN {account: m.id, holder: h.name, rule: al.rule_name} END) AS alerted_peers""",
             {"id": acc["account"]})[0]
    rows["alerted_peers"] = [x for x in rows["alerted_peers"] if x][:15]
    v = Viz()
    v.node(acc["account"], "Account", acc["name"], focus=True)
    for peer in rows["alerted_peers"]:
        v.node(peer["account"], "Account", peer["holder"] or peer["account"], alert=True)
        v.edge(acc["account"], peer["account"], "SAME_COMMUNITY")
    summary = (f"{acc['account']}: PageRank percentile {rows['pr_pct']:.0%}, betweenness percentile {rows['bt_pct']:.0%}; "
               f"community {rows['community']} has {rows['community_size']} accounts, {len(rows['alerted_peers'])} other alerted")
    return ToolResult(summary, rows, q.log, [acc["account"]] + [p["account"] for p in rows["alerted_peers"]], v, q.ms)


@tool("peer_comparison",
      "Compare a customer's 90-day inflow with peers of the same occupation or industry (graph peer group).",
      {"party_id": {"type": "string"}}, ["party_id"])
def peer_comparison(ctx: ToolContext, party_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    p = _resolve_party(q, party_id)
    grp = q("MATCH (p:Party {id: $id}) RETURN coalesce(p.occupation, p.industry) AS grp", {"id": p["party"]})[0]["grp"]
    rows = q("""
MATCH (peer:Customer) WHERE coalesce(peer.occupation, peer.industry) = $grp
MATCH (peer)-[:HOLDS]->(a:Account)
WITH peer, reduce(s = 0.0, x IN [(a)<-[t:TRANSFER]-() | t.amount] | s + x) +
           reduce(s = 0.0, x IN [(a)<-[c:CASH_DEPOSIT]-() | c.amount] | s + x) AS inflow
RETURN peer.id AS id, sum(inflow) AS inflow""", {"grp": grp})
    peers = sorted(r["inflow"] or 0 for r in rows if r["id"] != p["party"])
    subj = next((r["inflow"] or 0 for r in rows if r["id"] == p["party"]), 0)
    med = statistics.median(peers) if peers else 0
    p90 = peers[int(len(peers) * 0.9)] if peers else 0
    data = {"group": grp, "peers": len(peers), "subject_inflow_90d": round(subj), "peer_median": round(med),
            "peer_p90": round(p90), "ratio_to_median": round(subj / med, 2) if med else None}
    if peers:
        summary = (f"{p['name']} ({grp}): 90-day inflow {money(subj)} vs peer median {money(med)} across {len(peers)} peers"
                   + (f" ({data['ratio_to_median']}x)" if data["ratio_to_median"] else ""))
    else:
        summary = f"{p['name']} ({grp}): no peers with the same occupation/industry; 90-day inflow {money(subj)}"
    v = Viz()
    v.node(p["party"], "Person", p["name"], focus=True)
    return ToolResult(summary, data, q.log, [p["party"]], v, q.ms)


# ============================================================================ sanctions

@tool("sanctions_exposure",
      "Screen an account's counterparties (or a single company) for sanctions exposure through ownership chains. "
      "Applies the OFAC 50% rule: an entity is blocked when blocked persons own 50% or more of it in aggregate, "
      "directly or through other blocked entities. Reports partial (<50%) exposure too.",
      {"entity_id": {"type": "string", "description": "Account id to screen its counterparties, or a party id"}},
      ["entity_id"])
def sanctions_exposure(ctx: ToolContext, entity_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    if entity_id.startswith(("AC-", "EX-")):
        acc = _resolve_account(q, entity_id)
        targets = q("""MATCH (a:Account {id: $id})-[t:TRANSFER]-(x:Account)<-[:HOLDS]-(cp:Party)
                       RETURN cp.id AS id, cp.name AS name, x.id AS account, sum(t.amount) AS total,
                              x.country AS country""", {"id": acc["account"]})
        origin = acc["account"]
    else:
        p = _resolve_party(q, entity_id)
        targets = [{"id": p["party"], "name": p["name"], "account": None, "total": None, "country": None}]
        origin = p["party"]
    ids = [t["id"] for t in targets]
    edges = q("""
UNWIND $ids AS tid
MATCH (t:Party) WHERE t.id = tid
MATCH path = (o:Party)-[:OWNS*1..4]->(t)
UNWIND relationships(path) AS r
WITH DISTINCT startNode(r) AS owner, endNode(r) AS owned, r.pct AS pct
RETURN owner.id AS owner, owner.name AS owner_name, owner:Sanctioned AS owner_sanctioned,
       owner.program AS program, owner.list_id AS list_id, owned.id AS owned, owned.name AS owned_name, pct""",
              {"ids": ids})
    direct = q("""UNWIND $ids AS tid MATCH (t:Sanctioned {id: tid})
                  RETURN t.id AS id, t.name AS name, t.program AS program, t.list_id AS list_id""", {"ids": ids})
    # Fixed point: an entity is blocked if blocked owners hold >= 50% in aggregate (OFAC 2014 guidance).
    blocked = {e["owner"] for e in edges if e["owner_sanctioned"]} | {d["id"] for d in direct}
    names = {e["owner"]: e["owner_name"] for e in edges} | {e["owned"]: e["owned_name"] for e in edges}
    holdings: dict[str, list[dict]] = {}
    for e in edges:
        holdings.setdefault(e["owned"], []).append(e)
    changed = True
    while changed:
        changed = False
        for owned, hs in holdings.items():
            if owned not in blocked and sum(h["pct"] or 0 for h in hs if h["owner"] in blocked) >= 50:
                blocked.add(owned)
                changed = True
    results = []
    for t in targets:
        hs = holdings.get(t["id"], [])
        blocked_pct = sum(h["pct"] or 0 for h in hs if h["owner"] in blocked)
        status = ("LISTED" if t["id"] in {d["id"] for d in direct} else
                  "BLOCKED_50_RULE" if blocked_pct >= 50 else "PARTIAL_EXPOSURE" if blocked_pct > 0 else "CLEAR")
        if status == "CLEAR" and not hs:
            continue
        chains = []
        for h in hs:
            if h["owner"] in blocked:
                via = [x for x in holdings.get(h["owner"], []) if x["owner"] in blocked]
                chains.append({"owner": h["owner_name"], "pct": h["pct"],
                               "owner_is_listed": h["owner_sanctioned"], "program": h["program"], "list_id": h["list_id"],
                               "blocked_because": [f"{x['owner_name']} owns {x['pct']}%" for x in via] or None})
        results.append({"counterparty": t["name"], "party_id": t["id"], "account": t["account"],
                        "value_transacted": round(t["total"]) if t["total"] else None, "status": status,
                        "aggregate_blocked_ownership_pct": round(blocked_pct, 1), "blocked_owner_chains": chains})
    v = Viz()
    v.node(origin, "Account" if origin.startswith(("AC-", "EX-")) else "Company", origin, focus=True)
    for e in edges:
        v.node(e["owner"], "Sanctioned" if e["owner"] in blocked and e["owner_sanctioned"] else
               ("Blocked" if e["owner"] in blocked else "Company"), e["owner_name"])
        v.node(e["owned"], "Blocked" if e["owned"] in blocked else "Company", e["owned_name"])
        v.edge(e["owner"], e["owned"], "OWNS", pct=e["pct"])
    for t in targets:
        if t["account"] and t["id"] in holdings:
            v.node(t["account"], "External", t["name"], country=t["country"])
            v.edge(t["id"], t["account"], "HOLDS")
            v.edge(origin, t["account"], "TRANSFER", amount=t["total"])
    flagged = [r for r in results if r["status"] != "CLEAR"]
    summary = (f"Screened {len(targets)} counterpart(ies) of {origin} through up to 4 ownership hops: "
               + ("; ".join(f"{r['counterparty']} {r['status']} ({r['aggregate_blocked_ownership_pct']}% blocked ownership)"
                            for r in flagged) if flagged else "no sanctions exposure found"))
    ents = [origin] + ids + list(names)
    return ToolResult(summary, {"results": results, "blocked_entities": sorted(names.get(b, b) for b in blocked)},
                      q.log, ents, v, q.ms)


@tool("screen_names",
      "Fuzzy name screening of a party against designated (sanctioned) parties in the graph, comparing birth "
      "year and country to separate true matches from namesakes.",
      {"party_id": {"type": "string"}}, ["party_id"])
def screen_names(ctx: ToolContext, party_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    p = _resolve_party(q, party_id)
    subj = q("MATCH (p:Party {id: $id}) RETURN p.name AS name, p.birth_year AS by, p.country AS country", {"id": p["party"]})[0]
    lst = q("MATCH (s:Sanctioned) RETURN s.id AS id, s.name AS name, s.birth_year AS by, s.country AS country, s.program AS program, s.list_id AS list_id")
    hits = []
    for s in lst:
        score = SequenceMatcher(None, subj["name"].lower(), s["name"].lower()).ratio()
        if score >= 0.8:
            hits.append({**s, "name_similarity": round(score, 3),
                         "birth_year_match": subj["by"] == s["by"] if subj["by"] and s["by"] else None,
                         "country_match": subj["country"] == s["country"]})
    summary = (f"{subj['name']}: " + ("; ".join(f"possible match {h['name']} ({h['list_id']}, similarity {h['name_similarity']}, "
                                                 f"birth year match {h['birth_year_match']}, country match {h['country_match']})" for h in hits)
                                      if hits else "no designated-party name matches"))
    v = Viz()
    v.node(p["party"], "Person", subj["name"], focus=True)
    for h in hits:
        v.node(h["id"], "Sanctioned", h["name"])
        v.edge(p["party"], h["id"], "NAME_SIMILAR", score=h["name_similarity"])
    return ToolResult(summary, {"subject": subj, "hits": hits}, q.log, [p["party"]] + [h["id"] for h in hits], v, q.ms)


# ============================================================================ memory & consortium

@tool("recall_memory",
      "Recall what the bank already knows: prior cases (open or closed, with dispositions and summaries) and "
      "analyst lessons on these entities, plus cases on parties that share identifiers with them, plus the "
      "procedural playbook lessons for a typology.",
      {"entity_ids": {"type": "array", "items": {"type": "string"}, "description": "Party and/or account ids"},
       "typology": {"type": "string", "description": "Optional typology to fetch playbook lessons for"}},
      ["entity_ids"])
def recall_memory(ctx: ToolContext, entity_ids: list[str], typology: str | None = None) -> ToolResult:
    q = Q(ctx.tenant)
    ids = list(entity_ids)
    holders = q("UNWIND $ids AS x MATCH (p:Party)-[:HOLDS]->(:Account {id: x}) RETURN collect(DISTINCT p.id) AS ps", {"ids": ids})
    ids += holders[0]["ps"] if holders else []
    mem = memory.recall(ctx.tenant, ids)
    q.log.append(("// memory.recall(): prior cases via (:Case)-[:SUBJECT|CONCERNS]->(entity), linked cases via shared "
                  "identifiers, lessons via (:Lesson)-[:ABOUT]->(entity)", {"ids": ids}))
    mem["direct_cases"] = [c for c in mem["direct_cases"] if c["case_id"] != ctx.case_id]
    mem["linked_cases"] = [c for c in mem["linked_cases"] if c["case_id"] != ctx.case_id]
    if typology:
        mem["playbook"] = memory.playbook(ctx.tenant, typology)
    for c in mem["direct_cases"]:
        c["opened"] = fmt_ts(c.get("opened"))
    v = Viz()
    for c in mem["direct_cases"] + mem["linked_cases"]:
        v.node(c["case_id"], "Case", f"{c['case_id']} {c.get('disposition') or c.get('status')}")
        v.node(c["via"], "Account" if c["via"].startswith("AC-") else "Person", c["via"])
        v.edge(c["case_id"], c.get("linked_party") or c["via"], "SUBJECT")
    for l in mem["lessons"]:
        v.node(l["lesson_id"], "Lesson", l["text"][:60] + "...")
        v.edge(l["lesson_id"], l["about"], "ABOUT")
    parts = []
    if mem["direct_cases"]:
        parts.append("prior cases: " + "; ".join(f"{c['case_id']} {c.get('disposition') or c['status']} - {c.get('summary') or ''}"[:220]
                                                 for c in mem["direct_cases"]))
    if mem["linked_cases"]:
        parts.append("cases on linked parties: " + "; ".join(f"{c['case_id']} via shared {c['shared']}" for c in mem["linked_cases"][:5]))
    if mem["lessons"]:
        parts.append("analyst lessons: " + " | ".join(l["text"] for l in mem["lessons"]))
    if typology and mem.get("playbook", {}).get("lessons"):
        parts.append("playbook lessons: " + " | ".join(l["text"] for l in mem["playbook"]["lessons"]))
    summary = "Memory: " + ("; ".join(parts) if parts else "no prior cases or lessons on these entities")
    return ToolResult(summary, mem, q.log, ids, v, q.ms)


@tool("consortium_check",
      "Check a party's identifiers (device fingerprints, phones, IPs) against the cross-bank consortium graph. "
      "Identifiers are hashed with a shared key before lookup; only other institutions' reports are returned.",
      {"party_id": {"type": "string"}}, ["party_id"])
def consortium_check(ctx: ToolContext, party_id: str) -> ToolResult:
    q = Q(ctx.tenant)
    p = _resolve_party(q, party_id)
    idents = q("""MATCH (p:Party {id: $id})-[r:USES|HAS_PHONE|LOGGED_IN_FROM]->(i)
                  RETURN labels(i)[0] AS label, coalesce(i.fingerprint, i.number, i.addr) AS value""", {"id": p["party"]})
    kind_of = {"Device": "device", "Phone": "phone", "IP": "ip"}
    items = [(kind_of[i["label"]], i["value"]) for i in idents if i["value"]]
    hits = consortium.lookup(ctx.tenant, items)
    q.log.append(("// consortium graph (separate FalkorDB graph):\nUNWIND $hashes AS h MATCH (s:Signal {hash: h})<-[r:REPORTED]-(i:Institution)\n"
                  "WHERE i.id <> $tenant RETURN s.kind, i.name, r.typology, r.at", {"identifiers_hashed": len(items)}))
    for h in hits:
        h["reported_at"] = fmt_ts(h["reported_at"])
    v = Viz()
    v.node(p["party"], "Person", p["name"], focus=True)
    for h in hits:
        sid = f"SIG:{h['hash'][:8]}"
        v.node(sid, "Signal", f"{h['kind']} flagged by {h['institution']}")
        v.edge(p["party"], sid, "MATCHES_CONSORTIUM", typology=h["typology"])
    summary = (f"Checked {len(items)} hashed identifier(s) of {p['name']} against the consortium: "
               + ("; ".join(f"{h['kind']} {h['local_value']} reported by {h['institution']} for {h['typology']} on {h['reported_at']}" for h in hits)
                  if hits else "no matches from other institutions"))
    return ToolResult(summary, {"checked": len(items), "matches": hits}, q.log, [p["party"]], v, q.ms)


@tool("run_cypher",
      "Run a custom READ-ONLY Cypher query against the bank graph when no other tool fits. Executed with "
      "GRAPH.RO_QUERY so writes are rejected by FalkorDB. Results are capped at 50 rows. Schema: (:Party:Person|"
      ":Company[:Customer][:Sanctioned])-[:HOLDS]->(:Account[:External]); (:Account)-[:TRANSFER {amount, ts, "
      "channel, memo}]->(:Account); (:Branch)-[:CASH_DEPOSIT {amount, ts, ctr}]->(:Account); (:Party)-[:USES]->"
      "(:Device), -[:LOGGED_IN_FROM]->(:IP), -[:HAS_PHONE]->(:Phone), -[:LIVES_AT|REGISTERED_AT]->(:Address); "
      "(:Party)-[:OWNS {pct}|DIRECTOR_OF]->(:Company); (:Alert)-[:ON]->(:Account); (:Case)-[:SUBJECT|CONCERNS]->().",
      {"query": {"type": "string"}, "purpose": {"type": "string", "description": "What question this answers"}},
      ["query", "purpose"])
def run_cypher(ctx: ToolContext, query: str, purpose: str) -> ToolResult:
    q = Q(ctx.tenant)
    rows = q(query)
    rows = rows[:READ_ONLY_MAX_ROWS]
    ents = []
    for r in rows:
        for val in r.values():
            if isinstance(val, str) and val[:3] in ("AC-", "EX-", "P-1", "B-2"):
                ents.append(val)
    return ToolResult(f"Custom query ({purpose}): {len(rows)} row(s)", rows, q.log, ents, Viz(), q.ms)


# ============================================================================ write tools (actions)

@tool("record_finding",
      "Record a finding on the case. The claim must be a specific factual statement and must cite the "
      "evidence ids (EV-...) returned by earlier tool calls that prove it.",
      {"typology": {"type": "string", "enum": ["STRUCTURING", "MONEY_MULE", "ROUND_TRIPPING", "SANCTIONS_EVASION",
                                               "LAYERING", "SHELL_COMPANIES", "FRAUD_PROCEEDS", "BENIGN_EXPLANATION", "OTHER"]},
       "claim": {"type": "string"},
       "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
       "confidence": {"type": "number", "minimum": 0, "maximum": 1},
       "evidence_ids": {"type": "array", "items": {"type": "string"}}},
      ["typology", "claim", "severity", "confidence", "evidence_ids"], kind="write")
def record_finding(ctx: ToolContext, typology: str, claim: str, severity: str, confidence: float,
                   evidence_ids: list[str]) -> dict:
    return memory.record_finding(ctx.tenant, ctx.case_id, ctx.run_id, typology, claim, severity, confidence, evidence_ids)


@tool("consolidate_alerts",
      "Attach other open alerts on related accounts (same ring, same scheme) to this case so they are worked "
      "once instead of by several analysts. Returns the alerts that were merged.",
      {"account_ids": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}},
      ["account_ids", "reason"], kind="write")
def consolidate_alerts(ctx: ToolContext, account_ids: list[str], reason: str) -> dict:
    g = db.graph(ctx.tenant)
    rows, _ = db.rows(g, """UNWIND $ids AS x MATCH (al:Alert)-[:ON]->(a:Account {id: x})
                            WHERE al.status IN ['NEW', 'TRIAGED']
                            RETURN collect(al.id) AS alerts""", {"ids": account_ids})
    alerts = rows[0]["alerts"] if rows else []
    if alerts:
        memory.attach_alerts(ctx.tenant, ctx.case_id, alerts, reason)
    memory.link_subjects(ctx.tenant, ctx.case_id, [], account_ids)
    g.query("""MATCH (c:Case {id: $c}) UNWIND $ids AS x MATCH (p:Party)-[:HOLDS]->(:Account {id: x})
               MERGE (c)-[:SUBJECT]->(p)""", {"c": ctx.case_id, "ids": account_ids})
    return {"ok": True, "merged_alerts": alerts, "accounts_added": account_ids}


@tool("remember",
      "Save a durable lesson to memory, attached to the entities it is about (and optionally to a typology "
      "playbook), so future investigations by any agent recall it.",
      {"text": {"type": "string"}, "about_ids": {"type": "array", "items": {"type": "string"}},
       "typology": {"type": "string"}},
      ["text", "about_ids"], kind="write")
def remember(ctx: ToolContext, text: str, about_ids: list[str], typology: str | None = None) -> dict:
    lid = memory.add_lesson(ctx.tenant, text, author="hound-agent", about=about_ids,
                            refines=typology if typology in memory.PLAYBOOKS else None, case_id=ctx.case_id)
    return {"ok": True, "lesson_id": lid}


@tool("submit_disposition",
      "Finish the investigation. ESCALATE_SAR when suspicious activity is supported by findings; "
      "CLOSE_FALSE_POSITIVE when the activity has a verified legitimate explanation; MONITOR_EDD when "
      "unresolved risk remains. Provide the rationale and recommended actions. Call this exactly once, last.",
      {"disposition": {"type": "string", "enum": ["ESCALATE_SAR", "CLOSE_FALSE_POSITIVE", "MONITOR_EDD"]},
       "typologies": {"type": "array", "items": {"type": "string"}},
       "risk_score": {"type": "number", "minimum": 0, "maximum": 100},
       "rationale": {"type": "string", "description": "3-6 sentences citing evidence ids"},
       "recommended_actions": {"type": "array", "items": {"type": "string"}}},
      ["disposition", "typologies", "risk_score", "rationale", "recommended_actions"], kind="write")
def submit_disposition(ctx: ToolContext, disposition: str, typologies: list[str], risk_score: float,
                       rationale: str, recommended_actions: list[str]) -> dict:
    mapped = {"ESCALATE_SAR": "SAR_RECOMMENDED", "CLOSE_FALSE_POSITIVE": "FALSE_POSITIVE", "MONITOR_EDD": "MONITOR_EDD"}[disposition]
    memory.close_case(ctx.tenant, ctx.case_id, mapped, rationale, float(risk_score), typologies)
    db.graph(ctx.tenant).query("""MATCH (c:Case {id: $c}) SET c.recommended_actions = $a""",
                               {"c": ctx.case_id, "a": recommended_actions})
    return {"ok": True, "disposition": mapped, "case_id": ctx.case_id, "done": True}


def anthropic_tools(names: list[str] | None = None) -> list[dict]:
    specs = [TOOLS[n] for n in names] if names else list(TOOLS.values())
    return [s.anthropic() for s in specs]


def to_jsonable(x: Any) -> str:
    return json.dumps(x, default=str)
