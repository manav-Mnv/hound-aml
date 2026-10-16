"""Cross-institution signal sharing (FinCEN 314(b)-style) over a separate FalkorDB graph.

Each bank keeps its customers in its own isolated graph. Only keyed hashes of risky identifiers
(device fingerprints, phone numbers, IPs, external account numbers) are published to the shared
consortium graph, so one bank can learn "another member flagged this handset for mule activity"
without ever seeing the other bank's customer data.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from . import db
from .config import settings

KINDS = ("device", "phone", "ip", "email", "account")


def fingerprint(kind: str, value: str) -> str:
    normalized = value.strip().lower().replace(" ", "")
    mac = hmac.new(settings.consortium_key.encode(), f"{kind}:{normalized}".encode(), hashlib.sha256)
    return mac.hexdigest()


def publish(tenant: str, kind: str, value: str, *, typology: str, case_id: str,
            reported_at: int | None = None) -> str:
    h = fingerprint(kind, value)
    db.consortium().query("""
        MERGE (i:Institution {id: $tenant}) ON CREATE SET i.name = $name
        MERGE (s:Signal {hash: $hash}) ON CREATE SET s.kind = $kind, s.first_seen = $at
        MERGE (i)-[r:REPORTED {case_ref: $case}]->(s)
        SET r.typology = $typ, r.at = $at""",
                          {"tenant": tenant, "name": db.TENANT_NAMES.get(tenant, tenant), "hash": h,
                           "kind": kind, "at": reported_at or int(time.time()), "case": case_id,
                           "typ": typology})
    return h


def lookup(tenant: str, items: list[tuple[str, str]]) -> list[dict]:
    """Return consortium reports by *other* institutions for these (kind, value) identifiers."""
    hashes = {fingerprint(k, v): (k, v) for k, v in items}
    if not hashes:
        return []
    found, _ = db.rows(db.consortium(), """
        UNWIND $hashes AS h MATCH (s:Signal {hash: h})<-[r:REPORTED]-(i:Institution)
        WHERE i.id <> $tenant
        RETURN s.hash AS hash, s.kind AS kind, i.name AS institution, r.typology AS typology, r.at AS reported_at""",
                       {"hashes": list(hashes), "tenant": tenant})
    for f in found:
        kind, value = hashes[f["hash"]]
        f["local_value"] = value
        f["hash"] = f["hash"][:16] + "..."
    return found


def stats() -> dict:
    rows, _ = db.rows(db.consortium(), """
        MATCH (i:Institution) OPTIONAL MATCH (i)-[r:REPORTED]->(s:Signal)
        RETURN i.name AS institution, count(r) AS signals""")
    return {"institutions": rows}
