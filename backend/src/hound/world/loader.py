"""Load generated worlds into FalkorDB: one isolated graph per bank."""
from __future__ import annotations

import json
import time
from pathlib import Path

from falkordb import Graph

from .. import db, memory
from ..config import settings
from .generator import JURISDICTIONS, World, build_worlds

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

INDEXES = [
    "CREATE INDEX FOR (p:Party) ON (p.id)",
    "CREATE INDEX FOR (p:Party) ON (p.name)",
    "CREATE INDEX FOR (a:Account) ON (a.id)",
    "CREATE INDEX FOR (d:Device) ON (d.id)",
    "CREATE INDEX FOR (d:Device) ON (d.fingerprint)",
    "CREATE INDEX FOR (i:IP) ON (i.id)",
    "CREATE INDEX FOR (p:Phone) ON (p.id)",
    "CREATE INDEX FOR (e:Email) ON (e.id)",
    "CREATE INDEX FOR (a:Address) ON (a.id)",
    "CREATE INDEX FOR (b:Branch) ON (b.id)",
    "CREATE INDEX FOR (j:Jurisdiction) ON (j.code)",
    "CREATE INDEX FOR (al:Alert) ON (al.id)",
    "CREATE INDEX FOR (c:Case) ON (c.id)",
    "CREATE INDEX FOR (f:Finding) ON (f.id)",
    "CREATE INDEX FOR (e:Evidence) ON (e.id)",
    "CREATE INDEX FOR (r:AgentRun) ON (r.id)",
    "CREATE INDEX FOR (n:Lesson) ON (n.id)",
    "CREATE INDEX FOR (pb:Playbook) ON (pb.typology)",
    "CREATE INDEX FOR ()-[t:TRANSFER]-() ON (t.ts)",
    "CREATE INDEX FOR ()-[t:TRANSFER]-() ON (t.id)",
]

IDENT_LABEL_FOR_REL = {
    "USES": "Device", "LOGGED_IN_FROM": "IP", "HAS_PHONE": "Phone", "HAS_EMAIL": "Email",
    "LIVES_AT": "Address", "REGISTERED_AT": "Address",
}


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_") and v is not None}


def load_world(w: World) -> dict:
    g = db.graph(w.tenant)
    try:
        g.delete()
    except Exception:
        pass
    g = db.graph(w.tenant)
    started = time.perf_counter()
    for q in INDEXES:
        try:
            g.query(q)
        except Exception:
            pass

    g.query("UNWIND $rows AS r CREATE (:Jurisdiction {code: r.code, name: r.name, risk: r.risk})",
            {"rows": [{"code": c, **j} for c, j in JURISDICTIONS.items()]})

    # Parties: Person/Company, plus Customer and Sanctioned labels where they apply.
    for kind in ("Person", "Company"):
        for customer in (True, False):
            for sanctioned in (True, False):
                batch = [_clean(p) for p in w.parties if p["kind"] == kind and p["customer"] == customer
                         and bool(p.get("sanctioned")) == sanctioned]
                if not batch:
                    continue
                labels = f"{kind}:Party" + (":Customer" if customer else "") + (":Sanctioned" if sanctioned else "")
                db.batched(g, f"UNWIND $rows AS r CREATE (n:{labels}) SET n = r", batch)

    for external in (True, False):
        batch = [_clean(a) for a in w.accounts if a["external"] == external]
        labels = "Account:External" if external else "Account"
        db.batched(g, f"UNWIND $rows AS r CREATE (n:{labels}) SET n = r", batch)

    for label, items in w.identifiers.items():
        if items:
            db.batched(g, f"UNWIND $rows AS r CREATE (n:{label}) SET n = r", items)
    db.batched(g, "UNWIND $rows AS r CREATE (n:Branch) SET n = r", w.branches)
    g.query("""MATCH (a:Account), (j:Jurisdiction) WHERE j.code = a.country CREATE (a)-[:IN_JURISDICTION]->(j)""")
    g.query("""MATCH (p:Party), (j:Jurisdiction) WHERE j.code = p.country CREATE (p)-[:IN_JURISDICTION]->(j)""")

    for rel, links in w.links.items():
        if rel == "HOLDS":
            db.batched(g, """UNWIND $rows AS r MATCH (p:Party {id: r.src}) MATCH (a:Account {id: r.dst})
                             CREATE (p)-[:HOLDS]->(a)""", links)
        elif rel in ("OWNS", "DIRECTOR_OF"):
            db.batched(g, f"""UNWIND $rows AS r MATCH (p:Party {{id: r.src}}) MATCH (c:Party {{id: r.dst}})
                              CREATE (p)-[x:{rel}]->(c) SET x.pct = r.pct""", links)
        else:
            label = IDENT_LABEL_FOR_REL[rel]
            db.batched(g, f"""UNWIND $rows AS r MATCH (p:Party {{id: r.src}}) MATCH (i:{label} {{id: r.dst}})
                              MERGE (p)-[:{rel}]->(i)""", links)

    db.batched(g, """UNWIND $rows AS r MATCH (s:Account {id: r.src}) MATCH (d:Account {id: r.dst})
                     CREATE (s)-[:TRANSFER {id: r.id, amount: r.amount, ts: r.ts, channel: r.channel, memo: r.memo}]->(d)""",
               w.transfers, size=5000)
    db.batched(g, """UNWIND $rows AS r MATCH (b:Branch {id: r.src}) MATCH (d:Account {id: r.dst})
                     CREATE (b)-[:CASH_DEPOSIT {id: r.id, amount: r.amount, ts: r.ts, ctr: r.ctr}]->(d)""", w.cash)

    memory.ensure_playbooks(w.tenant, w.history.get("playbook_lessons", {}))
    for case in w.history.get("cases", []):
        memory.seed_closed_case(w.tenant, case)

    stats, _ = db.rows(g, "CALL db.meta.stats() YIELD nodeCount, relCount RETURN nodeCount, relCount")
    return {"tenant": w.tenant, "seconds": round(time.perf_counter() - started, 2), **stats[0]}


def seed(verbose: bool = True) -> dict:
    worlds = build_worlds()
    DATA_DIR.mkdir(exist_ok=True)
    truth = {t: w.truth for t, w in worlds.items()}
    (DATA_DIR / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    try:
        db.consortium().delete()
    except Exception:
        pass
    out = {}
    for tenant, w in worlds.items():
        out[tenant] = load_world(w)
        if verbose:
            print(f"loaded {settings.graph_name(tenant)}: {out[tenant]}")
    # Beta already filed a SAR on the earlier wave and shared hashed identifiers (314(b)).
    from .. import consortium
    for case in worlds["beta"].history.get("cases", []):
        for item in case.get("publish", []):
            consortium.publish("beta", item["kind"], item["value"], typology="MONEY_MULE",
                               case_id=case["id"], reported_at=case["closed"])
    return out
