"""HTTP API + live event stream (SSE) for the Hound web UI."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import consortium, db, memory, orchestrator, rules, tools, triage
from .agents import INVESTIGATOR_TOOLS
from .config import settings

from contextlib import asynccontextmanager

from .mcp_server import server as mcp_server

_mcp_app = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(_app):
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Hound", description="AML investigation agents on FalkorDB", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "dist"
DATA = Path(__file__).resolve().parents[2] / "data"


class Job:
    def __init__(self, tenant: str, alert_id: str):
        self.id = uuid.uuid4().hex[:12]
        self.tenant, self.alert_id = tenant, alert_id
        self.events: list[dict] = []
        self.done = False
        self.result: dict | None = None
        self.started = time.time()

    def emit(self, event: dict) -> None:
        event = {"seq": len(self.events), "t": round(time.time() - self.started, 2), **event}
        self.events.append(json.loads(json.dumps(event, default=str)))


JOBS: dict[str, Job] = {}


def _tenant(tenant: str) -> str:
    if tenant not in settings.tenants:
        raise HTTPException(404, f"unknown tenant {tenant}")
    return tenant


# ----------------------------------------------------------------------------- status & overview

@app.get("/api/status")
def status() -> dict:
    try:
        graphs = db.client().list_graphs()
        info = db.client().connection.execute_command("MODULE", "LIST")
        version = next((m[3] for m in info if m[1] in ("graph", b"graph")), None)
        ok = True
    except Exception as exc:
        graphs, version, ok = [], None, False
    ready_file = os.environ.get("HOUND_READY_FILE")
    ready = ok and (not ready_file or Path(ready_file).exists())
    return {"falkordb": ok, "falkordb_version": version, "graphs": graphs, "llm": settings.has_llm, "ready": ready,
            "model": settings.model if settings.has_llm else "offline playbook runner",
            "tenants": [{"id": t, "name": db.TENANT_NAMES[t]} for t in settings.tenants]}


@app.get("/api/{tenant}/overview")
def overview(tenant: str) -> dict:
    g = db.graph(_tenant(tenant))
    stats, _ = db.rows(g, "CALL db.meta.stats() YIELD labels, relTypes, nodeCount, relCount RETURN labels, relTypes, nodeCount, relCount")
    alerts, _ = db.rows(g, "MATCH (al:Alert) RETURN al.status AS status, count(*) AS n")
    cases, _ = db.rows(g, "MATCH (c:Case) RETURN c.disposition AS disposition, c.origin AS origin, count(*) AS n")
    groups, _ = db.rows(g, "MATCH (al:Alert) RETURN count(DISTINCT al.group) AS n")
    memory_counts, _ = db.rows(g, """OPTIONAL MATCH (l:Lesson) WITH count(l) AS lessons
                                     OPTIONAL MATCH (e:Evidence) WITH lessons, count(e) AS evidence
                                     OPTIONAL MATCH (r:AgentRun) WITH lessons, evidence, count(r) AS runs
                                     OPTIONAL MATCH (f:Finding) RETURN lessons, evidence, runs, count(f) AS findings""")
    return {"tenant": tenant, "name": db.TENANT_NAMES[tenant], "graph": settings.graph_name(tenant), **stats[0],
            "alerts": alerts, "cases": cases, "alert_groups": groups[0]["n"], "memory": memory_counts[0]}


# ----------------------------------------------------------------------------- alerts & triage

@app.get("/api/{tenant}/alerts")
def alerts(tenant: str) -> list[dict]:
    return triage.queue(_tenant(tenant))


@app.post("/api/{tenant}/triage")
def run_triage(tenant: str) -> dict:
    started = time.time()
    scored = triage.score_alerts(_tenant(tenant))
    return {"scored": len(scored), "ms": round((time.time() - started) * 1000)}


@app.post("/api/{tenant}/alerts/{alert_id}/investigate")
def investigate(tenant: str, alert_id: str, mode: str = "auto") -> dict:
    _tenant(tenant)
    job = Job(tenant, alert_id)
    JOBS[job.id] = job

    def work():
        try:
            job.result = orchestrator.investigate(tenant, alert_id, job.emit, mode=mode)
        except Exception as exc:
            traceback.print_exc()
            job.emit({"type": "error", "agent": "orchestrator", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            job.done = True
            job.emit({"type": "end", "result": job.result})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")

    async def stream():
        sent = 0
        while True:
            while sent < len(job.events):
                yield f"data: {json.dumps(job.events[sent])}\n\n"
                sent += 1
            if job.done and sent >= len(job.events):
                break
            await asyncio.sleep(0.15)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------------------- cases

@app.get("/api/{tenant}/cases")
def cases(tenant: str) -> list[dict]:
    rows = orchestrator.list_cases(_tenant(tenant))
    for r in rows:
        r["subjects"] = r["subjects"][:4]
    return rows


@app.get("/api/{tenant}/cases/{case_id}")
def case(tenant: str, case_id: str) -> dict:
    try:
        return orchestrator.case_detail(_tenant(tenant), case_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


class Decision(BaseModel):
    decision: str
    analyst: str = "analyst"
    note: str = ""


@app.post("/api/{tenant}/cases/{case_id}/decision")
def decide(tenant: str, case_id: str, body: Decision) -> dict:
    try:
        return orchestrator.decide(_tenant(tenant), case_id, body.decision, body.analyst, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ----------------------------------------------------------------------------- exploration

KIND_ORDER = ["Sanctioned", "External", "Company", "Person", "Account", "Device", "IP", "Phone", "Email", "Address",
              "Branch", "Case", "Lesson", "Alert", "Jurisdiction", "Playbook", "Finding", "SAR", "AgentRun", "Evidence"]


def _kind(labels: list[str]) -> str:
    return next((k for k in KIND_ORDER if k in labels), labels[0] if labels else "Node")


def _label(n: dict) -> str:
    return n.get("name") or n.get("line") or n.get("fingerprint") or n.get("addr") or n.get("number") or \
        n.get("text", "")[:40] or n.get("id") or n.get("code") or n.get("typology") or "?"


@app.get("/api/{tenant}/entity/{entity_id}/neighborhood")
def neighborhood(tenant: str, entity_id: str, limit: int = 60) -> dict:
    g = db.graph(_tenant(tenant))
    rows, _ = db.rows(g, """
        OPTIONAL MATCH (p:Party {id: $id}) OPTIONAL MATCH (a:Account {id: $id})
        WITH coalesce(p, a) AS n WHERE n IS NOT NULL
        MATCH (n)-[r]-(m)
        WHERE NOT m:Evidence AND NOT m:AgentRun AND NOT m:Jurisdiction
        RETURN n, type(r) AS rel, startNode(r) = n AS outgoing, r.amount AS amount, r.ts AS ts, r.pct AS pct, m
        LIMIT $limit""", {"id": entity_id, "limit": limit})
    nodes, edges = {}, {}
    for r in rows:
        for x in (r["n"], r["m"]):
            nid = x.get("id") or x.get("code")
            nodes[nid] = {"id": nid, "kind": _kind(x["labels"]), "label": _label(x), "country": x.get("country")}
        a, b = r["n"].get("id"), r["m"].get("id") or r["m"].get("code")
        src, dst = (a, b) if r["outgoing"] else (b, a)
        key = f"{src}|{r['rel']}|{dst}|{r['ts']}"
        edges[key] = {"id": key, "source": src, "target": dst, "rel": r["rel"], "amount": r["amount"], "pct": r["pct"]}
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


@app.get("/api/{tenant}/memory")
def memory_graph(tenant: str) -> dict:
    """The agents' memory as a graph: cases, findings, lessons, playbooks, agent runs and what they hang off."""
    g = db.graph(_tenant(tenant))
    rows, _ = db.rows(g, """
        MATCH (x)-[r]->(y)
        WHERE (x:Case OR x:Lesson OR x:AgentRun OR x:SAR OR x:Finding)
          AND type(r) IN ['SUBJECT', 'FROM_ALERT', 'ABOUT', 'REFINES', 'LEARNED_FROM', 'WORKED_ON', 'HANDOFF',
                          'HAS_FINDING', 'FOR_CASE']
        RETURN x, type(r) AS rel, y LIMIT 1500""")
    nodes, edges = {}, {}
    for r in rows:
        for n in (r["x"], r["y"]):
            nid = n.get("id") or n.get("typology")
            kind = _kind(n["labels"])
            nodes[nid] = {"id": nid, "kind": kind, "label": n.get("agent") or n.get("name") or _label(n) if kind != "Case" else nid,
                          "disposition": n.get("disposition"), "status": n.get("status"), "origin": n.get("origin"),
                          "text": n.get("text") or n.get("summary") or n.get("claim")}
        a = r["x"].get("id") or r["x"].get("typology")
        b = r["y"].get("id") or r["y"].get("typology")
        edges[f"{a}|{r['rel']}|{b}"] = {"id": f"{a}|{r['rel']}|{b}", "source": a, "target": b, "rel": r["rel"]}
    playbooks = {t: memory.playbook(tenant, t) for t in memory.PLAYBOOKS}
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "playbooks": playbooks}


@app.get("/api/{tenant}/evidence/{evidence_id}")
def evidence(tenant: str, evidence_id: str) -> dict:
    rows, _ = db.rows(db.graph(_tenant(tenant)), """MATCH (e:Evidence {id: $id})
        RETURN e.id AS id, e.tool AS tool, e.summary AS summary, e.cypher AS cypher, e.params AS params,
               e.ms AS ms, e.rows AS rows, e.graph AS graph, e.data AS data""", {"id": evidence_id})
    if not rows:
        raise HTTPException(404, "unknown evidence")
    e = rows[0]
    e["graph"] = json.loads(e["graph"]) if e.get("graph") else {"nodes": [], "edges": []}
    e["data"] = json.loads(e["data"]) if e.get("data") else None
    return e


@app.get("/api/consortium")
def consortium_view() -> dict:
    rows, _ = db.rows(db.consortium(), """MATCH (i:Institution)-[r:REPORTED]->(s:Signal)
        RETURN i.id AS institution, i.name AS name, s.kind AS kind, substring(s.hash, 0, 16) AS hash,
               r.typology AS typology, r.at AS at, r.case_ref AS case_ref ORDER BY at""")
    return {"graph": settings.consortium_graph, "signals": rows, **consortium.stats()}


@app.get("/api/eval")
def eval_results() -> dict:
    out = {}
    for f in sorted(DATA.glob("eval_*.json")):
        out[f.stem.removeprefix("eval_")] = json.loads(f.read_text())
    return out


@app.get("/api/schema")
def schema() -> dict:
    g = db.graph("alpha")
    labels, _ = db.rows(g, "CALL db.labels() YIELD label RETURN collect(label) AS labels")
    rels, _ = db.rows(g, "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS rels")
    tool_list = [{"name": n, "description": tools.TOOLS[n].description, "kind": tools.TOOLS[n].kind} for n in INVESTIGATOR_TOOLS]
    return {"labels": labels[0]["labels"], "relationships": rels[0]["rels"], "rules": rules.rule_cypher(), "tools": tool_list}


@app.post("/api/admin/reset")
def reset() -> dict:
    if os.environ.get("HOUND_ALLOW_RESET", "1") != "1":
        raise HTTPException(403, "reset disabled")
    from . import analytics
    from .world.loader import seed
    seed(verbose=False)
    for t in settings.tenants:
        analytics.run_analytics(t)
        rules.run_rules(t)
        triage.score_alerts(t)
    return {"ok": True}


# ----------------------------------------------------------------------------- frontend

app.mount("/mcp-server", _mcp_app)

if FRONTEND.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = FRONTEND / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND / "index.html")
