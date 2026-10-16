"""Synthetic banking world with planted money-laundering typologies.

Everything here is fictional. Phone numbers use the reserved 555-01xx range, e-mails use
RFC 2606 domains, IPs come from the RFC 5737 documentation ranges, and the risky
jurisdictions use ISO 3166 user-assigned codes (XQ, XT, XV) so no real country is labelled.

Each bank only sees transactions that touch its own accounts, like a real bank. Ground truth
for every planted scenario is returned separately and never written into the graph.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from faker import Faker

DAY = 86_400
HOUR = 3_600
SIM_END = int(datetime(2026, 10, 14, tzinfo=timezone.utc).timestamp())
SIM_DAYS = 90
T0 = SIM_END - SIM_DAYS * DAY

JURISDICTIONS = {
    "US": {"name": "United States", "risk": "low"},
    "CA": {"name": "Canada", "risk": "low"},
    "GB": {"name": "United Kingdom", "risk": "low"},
    "DE": {"name": "Germany", "risk": "low"},
    "IN": {"name": "India", "risk": "low"},
    "SG": {"name": "Singapore", "risk": "low"},
    # Fictional jurisdictions (ISO user-assigned codes) standing in for high-risk / secrecy havens.
    "XQ": {"name": "Qastria (fictional)", "risk": "high"},
    "XT": {"name": "Tessaly Islands (fictional)", "risk": "high"},
    "XV": {"name": "Varnholm (fictional secrecy haven)", "risk": "high"},
}
HIGH_RISK = {code for code, j in JURISDICTIONS.items() if j["risk"] == "high"}

OCCUPATIONS = [
    ("Teacher", 2100), ("Nurse", 2600), ("Software Engineer", 4300), ("Retail Associate", 1500),
    ("Electrician", 2500), ("Accountant", 3100), ("Truck Driver", 2300), ("Pharmacist", 4000),
    ("Chef", 1900), ("Graphic Designer", 2400), ("Mechanic", 2200), ("Paralegal", 2300),
    ("Dental Hygienist", 2700), ("Sales Manager", 3600), ("Barista", 1300), ("Civil Engineer", 3800),
]
CITIES = ["Riverton", "Lakeside", "Brookfield", "Fairview", "Oakdale", "Millbrook", "Westport", "Cedar Falls"]


@dataclass
class World:
    tenant: str
    parties: list[dict] = field(default_factory=list)      # Person / Company nodes
    accounts: list[dict] = field(default_factory=list)
    identifiers: dict[str, list[dict]] = field(default_factory=lambda: {
        "Device": [], "IP": [], "Phone": [], "Email": [], "Address": []})
    branches: list[dict] = field(default_factory=list)
    links: dict[str, list[dict]] = field(default_factory=dict)  # rel type -> [{src, dst, ...props}]
    transfers: list[dict] = field(default_factory=list)
    cash: list[dict] = field(default_factory=list)
    truth: dict[str, dict] = field(default_factory=dict)
    history: dict = field(default_factory=dict)             # seeds for prior cases (memory)
    shared: dict = field(default_factory=dict)              # identifiers reused across banks

    def link(self, rel: str, src: str, dst: str, **props) -> None:
        self.links.setdefault(rel, []).append({"src": src, "dst": dst, **props})


class Builder:
    """Shared machinery: id allocation, parties, accounts, identifiers, transactions."""

    def __init__(self, tenant: str, seed: int, bank_name: str, routing: str):
        self.w = World(tenant)
        self.rng = random.Random(seed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(seed)
        self.bank_name = bank_name
        self.routing = routing
        self._counters: dict[str, int] = {}
        self.party_by_id: dict[str, dict] = {}
        self.accounts_of: dict[str, list[str]] = {}
        self._phone_seq = self.rng.randint(0, 50)
        self._ip_seq = 0
        self._ips_seen: set[str] = set()
        self._phones_seen: set[str] = set()

    # ---------- ids ----------
    def next_id(self, prefix: str, start: int, step_max: int = 7) -> str:
        n = self._counters.get(prefix, start) + self.rng.randint(1, step_max)
        self._counters[prefix] = n
        return f"{prefix}-{n}"

    def after(self, ts: int, lo_hours: float, hi_hours: float) -> int:
        """A timestamp a random number of hours after another one (keeps chains ordered)."""
        return int(ts + self.rng.uniform(lo_hours, hi_hours) * HOUR)

    def ts(self, day: float, hour_lo: int = 8, hour_hi: int = 20) -> int:
        day = max(0.0, min(SIM_DAYS - 0.01, day))
        base = T0 + int(day) * DAY
        return base + self.rng.randint(hour_lo * HOUR, hour_hi * HOUR - 1)

    # ---------- parties ----------
    def person(self, *, customer: bool = True, name: str | None = None, age: int | None = None,
               occupation: str | None = None, tenure_days: int | None = None, country: str = "US",
               risk: str = "low", **extra) -> dict:
        age = age or self.rng.randint(22, 78)
        occ, pay = (occupation, None) if occupation else self.rng.choice(OCCUPATIONS)
        tenure = tenure_days if tenure_days is not None else self.rng.randint(200, 4200)
        p = {
            "id": self.next_id("P", 10_000), "kind": "Person", "customer": customer,
            "name": name or self.fake.name(), "age": age, "birth_year": 2026 - age,
            "occupation": occ, "country": country,
            "onboarded": SIM_END - tenure * DAY if customer else None,
            "risk_rating": risk, "pep": False, "_pay": pay,
        }
        p.update(extra)
        self._add_party(p)
        return p

    def company(self, *, customer: bool = True, name: str | None = None, industry: str = "Services",
                jurisdiction: str = "US", incorporated_days_ago: int | None = None,
                tenure_days: int | None = None, risk: str = "low", **extra) -> dict:
        inc = incorporated_days_ago if incorporated_days_ago is not None else self.rng.randint(800, 9000)
        tenure = tenure_days if tenure_days is not None else min(inc, self.rng.randint(300, 3000))
        c = {
            "id": self.next_id("B", 20_000), "kind": "Company", "customer": customer,
            "name": name or self.fake.company(), "industry": industry, "country": jurisdiction,
            "incorporated": SIM_END - inc * DAY,
            "onboarded": SIM_END - tenure * DAY if customer else None,
            "risk_rating": risk, "registry_id": f"REG-{jurisdiction}-{self.rng.randint(100000, 999999)}",
        }
        c.update(extra)
        self._add_party(c)
        return c

    def _add_party(self, p: dict) -> None:
        self.w.parties.append(p)
        self.party_by_id[p["id"]] = p

    # ---------- accounts ----------
    def account(self, owner: dict, *, kind: str | None = None, opened_days_ago: int | None = None,
                external: bool = False, bank: str | None = None, country: str | None = None) -> str:
        if external:
            acc_id = self.next_id("EX", 700_000, 13)
        else:
            acc_id = self.next_id("AC", 300_000, 11)
        if opened_days_ago is None:
            onboard = owner.get("onboarded") or (SIM_END - 2000 * DAY)
            opened = onboard + self.rng.randint(0, 20) * DAY
            opened = min(opened, SIM_END - 5 * DAY)
        else:
            opened = SIM_END - opened_days_ago * DAY
        a = {
            "id": acc_id, "owner": owner["id"], "external": external,
            "type": kind or ("business" if owner["kind"] == "Company" else "checking"),
            "opened": opened, "status": "open",
            "bank": bank or (self.bank_name if not external else "Other Bank"),
            "country": country or owner.get("country", "US"),
        }
        self.w.accounts.append(a)
        self.accounts_of.setdefault(owner["id"], []).append(acc_id)
        self.w.link("HOLDS", owner["id"], acc_id)
        return acc_id

    def primary(self, party: dict) -> str:
        return self.accounts_of[party["id"]][0]

    # ---------- identifiers ----------
    def device(self, fingerprint: str | None = None, os_name: str | None = None) -> str:
        fp = fingerprint or hashlib.sha1(f"{self.w.tenant}-{self.rng.random()}".encode()).hexdigest()[:16]
        d = {"id": self.next_id("DV", 50_000), "fingerprint": fp,
             "os": os_name or self.rng.choice(["iOS 19", "Android 16", "Windows 11", "macOS 16"])}
        self.w.identifiers["Device"].append(d)
        return d["id"]

    def ip(self, addr: str | None = None) -> str:
        if addr is None:
            # Ordinary customers get unique IPv6 documentation addresses (RFC 3849); the IPv4
            # documentation ranges are reserved for the few deliberately shared addresses.
            self._ip_seq += 1
            addr = f"2001:db8:{self.w.tenant[0]}a:{self._ip_seq:x}::1"
        if addr not in self._ips_seen:
            self._ips_seen.add(addr)
            self.w.identifiers["IP"].append({"id": addr, "addr": addr})
        return addr

    def phone(self, number: str | None = None) -> str:
        if number is None:
            self._phone_seq += 1
            area = 200 + (self._phone_seq // 100) % 700
            number = f"+1-{area}-555-01{self._phone_seq % 100:02d}"
        if number not in self._phones_seen:
            self._phones_seen.add(number)
            self.w.identifiers["Phone"].append({"id": number, "number": number})
        return number

    def email(self, party: dict, addr: str | None = None) -> str:
        if addr is None:
            local = "".join(ch for ch in party["name"].lower().replace(" ", ".") if ch.isalnum() or ch == ".")
            addr = f"{local}{self.rng.randint(1, 999)}@{self.rng.choice(['example.com', 'example.net', 'example.org'])}"
        self.w.identifiers["Email"].append({"id": addr, "addr": addr})
        return addr

    def address(self, city: str | None = None, country: str = "US", line: str | None = None) -> str:
        a = {"id": self.next_id("AD", 80_000), "line": line or self.fake.street_address(),
             "city": city or self.rng.choice(CITIES), "country": country}
        self.w.identifiers["Address"].append(a)
        return a["id"]

    def kyc_identity(self, p: dict, *, device: str | None = None, address: str | None = None,
                     ip: str | None = None, phone: str | None = None) -> None:
        """Give a customer the usual identifiers, optionally sharing some."""
        self.w.link("USES", p["id"], device or self.device())
        self.w.link("LOGGED_IN_FROM", p["id"], ip or self.ip())
        self.w.link("HAS_PHONE", p["id"], phone or self.phone())
        self.w.link("HAS_EMAIL", p["id"], self.email(p))
        rel = "LIVES_AT" if p["kind"] == "Person" else "REGISTERED_AT"
        self.w.link(rel, p["id"], address or self.address())

    # ---------- money ----------
    def transfer(self, src: str, dst: str, amount: float, ts: int, channel: str = "ach", memo: str = "") -> None:
        self.w.transfers.append({
            "id": f"TX-{len(self.w.transfers) + 1:07d}", "src": src, "dst": dst,
            "amount": round(float(amount), 2), "ts": int(ts), "channel": channel, "memo": memo,
        })

    def cash_deposit(self, branch: str, dst: str, amount: float, ts: int) -> None:
        self.w.cash.append({
            "id": f"CD-{len(self.w.cash) + 1:06d}", "src": branch, "dst": dst,
            "amount": round(float(amount), 2), "ts": int(ts), "ctr": amount > 10_000,
        })

    def branches(self, n: int) -> list[str]:
        out = []
        for i in range(n):
            b = {"id": f"BR-{self.w.tenant[:1].upper()}{i + 1:02d}", "city": CITIES[i % len(CITIES)],
                 "kind": "branch" if i % 3 else "atm"}
            self.w.branches.append(b)
            out.append(b["id"])
        return out

    def scenario(self, key: str, typology: str, title: str, accounts: list[str], parties: list[str],
                 description: str) -> None:
        self.w.truth[key] = {"typology": typology, "title": title, "accounts": sorted(set(accounts)),
                             "parties": sorted(set(parties)), "description": description}


# =====================================================================================
# Alpha Bank: the main stage
# =====================================================================================

def build_alpha(seed: int = 7) -> World:
    b = Builder("alpha", seed, "Alpha Bank", "021000999")
    rng = b.rng
    branches = b.branches(9)

    # ---------- external counterparties ----------
    employers = [b.company(customer=False, industry="Employer") for _ in range(38)]
    landlords = [b.company(customer=False, industry="Property Management") for _ in range(14)]
    utilities = [b.company(customer=False, name=n, industry="Utilities") for n in
                 ["Riverton Power & Light", "Lakeside Water Authority", "Brightwave Telecom", "Cedar Gas Co"]]
    merchants = [b.company(customer=False, industry=ind) for ind in
                 ["Grocery", "Grocery", "Fuel", "Pharmacy", "Restaurants", "Online Marketplace",
                  "Card Settlement", "Home Improvement", "Electronics", "Apparel"]]
    title_cos = [b.company(customer=False, name="Keystone Title & Escrow", industry="Title & Escrow"),
                 b.company(customer=False, name="Harborview Settlement Services", industry="Title & Escrow")]
    for c in employers + landlords + utilities + merchants + title_cos:
        b.account(c, external=True, bank=rng.choice(["First Union Trust", "Pacific Commerce Bank", "Summit National"]))

    # Foreign/private counterparties used by noise events.
    universities = [b.company(customer=False, name="Qastria Institute of Technology", industry="Education",
                              jurisdiction="XQ")]
    b.account(universities[0], external=True, bank="Qastria National Bank", country="XQ")

    # ---------- retail customers ----------
    persons: list[dict] = []
    for _ in range(1050):
        p = b.person()
        b.account(p)
        if rng.random() < 0.35:
            b.account(p, kind="savings")
        persons.append(p)

    # Households share an address and often a family tablet: realistic shared-identifier noise.
    rng.shuffle(persons)
    hh_members: set[str] = set()
    idx = 0
    for _ in range(70):
        size = rng.choice([2, 2, 3])
        members = persons[idx: idx + size]
        idx += size
        addr = b.address()
        family_device = b.device(os_name="iPadOS 19") if rng.random() < 0.45 else None
        home_ip = b.ip()
        surname = members[0]["name"].split()[-1]
        for m in members:
            m["name"] = " ".join(m["name"].split()[:-1] + [surname])
            b.kyc_identity(m, address=addr, ip=home_ip)
            if family_device:
                b.w.link("USES", m["id"], family_device)
            hh_members.add(m["id"])
    for p in persons[idx:]:
        b.kyc_identity(p)

    # ---------- business customers ----------
    industries = ["Restaurant", "Salon", "Auto Repair", "Dental Practice", "Landscaping", "Bakery",
                  "IT Consulting", "Florist", "Fitness Studio", "Printing", "Plumbing", "Daycare"]
    businesses = []
    for _ in range(70):
        c = b.company(industry=rng.choice(industries))
        b.account(c)
        b.kyc_identity(c)
        owner = rng.choice(persons)
        b.w.link("OWNS", owner["id"], c["id"], pct=100.0)
        b.w.link("DIRECTOR_OF", owner["id"], c["id"])
        businesses.append(c)

    # ---------- background activity ----------
    for p in persons:
        acc = b.primary(p)
        employer = rng.choice(employers)
        pay = p["_pay"] or rng.choice(OCCUPATIONS)[1]
        p["expected_monthly_inflow"] = round(pay * 2.17, -2)
        pay_day = rng.randint(0, 13)
        for d in range(pay_day, SIM_DAYS, 14):
            b.transfer(b.primary(employer), acc, pay * rng.uniform(0.97, 1.03), b.ts(d, 1, 5), "ach", "PAYROLL")
        rent = round(pay * rng.uniform(0.45, 0.8), -1)
        landlord = rng.choice(landlords)
        for m in range(3):
            b.transfer(acc, b.primary(landlord), rent, b.ts(m * 30 + rng.randint(0, 3)), "ach", "RENT")
        for u in rng.sample(utilities, 2):
            for m in range(3):
                b.transfer(acc, b.primary(u), rng.uniform(45, 230), b.ts(m * 30 + rng.randint(5, 20)), "ach", "UTILITY")
        for wk in range(0, SIM_DAYS, 7):
            if rng.random() < 0.8:
                b.transfer(acc, b.primary(rng.choice(merchants)), rng.uniform(40, 420), b.ts(wk + rng.randint(0, 6)), "card", "CARD")
        if len(b.accounts_of[p["id"]]) > 1 and rng.random() < 0.7:
            for m in range(3):
                b.transfer(acc, b.accounts_of[p["id"]][1], round(pay * rng.uniform(0.05, 0.2), -1),
                           b.ts(m * 30 + 16), "internal", "SAVINGS")
        if rng.random() < 0.18:
            for _ in range(rng.randint(1, 3)):
                b.cash_deposit(rng.choice(branches), acc, rng.uniform(80, 2600), b.ts(rng.uniform(0, 89)))
    # P2P between friends.
    for _ in range(4200):
        a, c = rng.sample(persons, 2)
        b.transfer(b.primary(a), b.primary(c), rng.choice([20, 25, 40, 50, 60, 75, 100, 150, 200, 300]),
                   b.ts(rng.uniform(0, 89)), "p2p", rng.choice(["dinner", "rent split", "tickets", "thanks!", "gas", ""]))
    # Businesses: customer receipts, suppliers, owner draws.
    for c in businesses:
        acc = b.primary(c)
        for d in range(0, SIM_DAYS, 3):
            b.transfer(b.primary(rng.choice(merchants[6:7])), acc, rng.uniform(900, 4200), b.ts(d), "ach", "CARD SETTLEMENT")
        for m in range(3):
            b.transfer(acc, b.primary(rng.choice(landlords)), rng.uniform(2500, 6000), b.ts(m * 30 + 2), "ach", "LEASE")
            owner = b.w.links["OWNS"][[l["dst"] for l in b.w.links["OWNS"]].index(c["id"])]["src"]
            b.transfer(acc, b.primary(b.party_by_id[owner]), rng.uniform(2000, 7000), b.ts(m * 30 + 25), "internal", "OWNER DRAW")

    # =================================================================================
    # Benign look-alikes (false-positive bait). Each has a verifiable innocent explanation.
    # =================================================================================
    # B1: payroll processor with massive fan-out, reviewed before.
    payroll = b.company(name="Brightline Payroll Services Inc", industry="Payroll Processing",
                        incorporated_days_ago=4100, tenure_days=2300)
    b.account(payroll)
    b.kyc_identity(payroll)
    payroll["expected_activity"] = "Processes payroll for ~40 small employers; bi-weekly ACH batches to employees."
    clients = rng.sample(businesses, 12)
    workers = rng.sample(persons, 160)
    for d in range(4, SIM_DAYS, 14):
        total = 0.0
        for wk in workers:
            amt = rng.uniform(900, 2600)
            total += amt
            b.transfer(b.primary(payroll), b.primary(wk), amt, b.ts(d, 1, 4), "ach", "PAYROLL BRIGHTLINE")
        for cl in clients:
            b.transfer(b.primary(cl), b.primary(payroll), total / len(clients) * 1.01, b.ts(d - 1, 9, 12), "ach", "PAYROLL FUNDING")
    b.w.history["payroll"] = {"party": payroll["id"], "account": b.primary(payroll)}

    # B2: cash-intensive convenience store (deposits above and below the CTR threshold).
    mart = b.company(name="Sunrise Mini Mart LLC", industry="Convenience Store", tenure_days=1900)
    b.account(mart)
    b.kyc_identity(mart)
    mart["expected_activity"] = "Cash-intensive retail; daily cash deposits $2k-$14k; files CTRs regularly."
    mart_branch = branches[2]
    for d in range(SIM_DAYS):
        if d % 7 != 6:
            amt = rng.choice([rng.uniform(1800, 7000), rng.uniform(6000, 9900), rng.uniform(9000, 14500)])
            b.cash_deposit(mart_branch, b.primary(mart), amt, b.ts(d, 17, 20))
    for m in range(3):
        b.transfer(b.primary(mart), b.primary(rng.choice(merchants[:2])), rng.uniform(30000, 52000), b.ts(m * 30 + 10), "wire", "WHOLESALE INVENTORY")
    owner = rng.choice([p for p in persons if p["id"] not in hh_members])
    b.w.link("OWNS", owner["id"], mart["id"], pct=100.0)
    b.w.link("DIRECTOR_OF", owner["id"], mart["id"])
    b.w.history["mart"] = {"party": mart["id"], "account": b.primary(mart)}

    # B3: small businesses with occasional big cash days (restaurants after events).
    for c in rng.sample(businesses, 7):
        for _ in range(2):
            d = rng.uniform(5, 85)
            b.cash_deposit(rng.choice(branches), b.primary(c), rng.uniform(8100, 9800), b.ts(d, 17, 20))
            b.cash_deposit(rng.choice(branches), b.primary(c), rng.uniform(8100, 9800), b.ts(d + rng.uniform(1, 5), 17, 20))
            b.cash_deposit(rng.choice(branches), b.primary(c), rng.uniform(10500, 16000), b.ts(d + 6, 17, 20))

    # B4: life events -> many senders in one week (weddings, fundraisers, club dues).
    for p in rng.sample(persons, 16):
        d = rng.uniform(5, 80)
        for friend in rng.sample(persons, rng.randint(7, 12)):
            b.transfer(b.primary(friend), b.primary(p), rng.choice([50, 75, 100, 150, 200, 250]),
                       b.ts(d + rng.uniform(0, 5)), "p2p", rng.choice(["wedding gift", "congrats!", "fundraiser", "club dues"]))

    # B5: real-estate closing: sale proceeds in, purchase out via title companies.
    for p in rng.sample([x for x in persons if x["age"] > 35], 5):
        d = rng.uniform(10, 80)
        sale = round(rng.uniform(280_000, 520_000), -2)
        b.transfer(b.primary(title_cos[0]), b.primary(p), sale, b.ts(d), "wire", "SALE PROCEEDS 41 ELM ST")
        b.transfer(b.primary(p), b.primary(title_cos[1]), sale * rng.uniform(0.82, 0.96), b.ts(d + 1.5), "wire", "CLOSING FUNDS PURCHASE")

    # B6: tuition / family support wires to a high-risk (fictional) jurisdiction, with memos.
    for p in rng.sample(persons, 6):
        b.transfer(b.primary(p), b.primary(universities[0]), rng.uniform(25_500, 41_000), b.ts(rng.uniform(5, 60)),
                   "wire", "TUITION FALL 2026 STUDENT ID 88" + str(rng.randint(1000, 9999)))

    # B7: established importer that has paid a Tessaly supplier for years.
    importer = b.company(name="Harbor Lane Seafood Importers", industry="Seafood Import", tenure_days=3100)
    b.account(importer)
    b.kyc_identity(importer)
    importer["expected_activity"] = "Imports seafood; monthly supplier wires to XT (Tessaly) $30k-$60k."
    supplier = b.company(customer=False, name="Tessaly Fisheries Cooperative", industry="Fisheries", jurisdiction="XT")
    b.account(supplier, external=True, bank="Tessaly Commercial Bank", country="XT")
    for m in range(3):
        b.transfer(b.primary(importer), b.primary(supplier), rng.uniform(31_000, 58_000), b.ts(m * 30 + 12), "wire", f"INV TF-{2400 + m}")
        for _ in range(8):
            b.transfer(b.primary(rng.choice(merchants[:2])), b.primary(importer), rng.uniform(8000, 15000), b.ts(m * 30 + rng.uniform(0, 29)), "ach", "WHOLESALE RECEIPT")

    # B8: new customers with large legitimate inflows (inheritance, bonus, house sale).
    for _ in range(5):
        p = b.person(tenure_days=rng.randint(20, 70))
        b.account(p)
        b.kyc_identity(p)
        b.transfer(b.primary(rng.choice(title_cos + employers[:3])), b.primary(p), rng.uniform(36_000, 140_000),
                   b.ts(rng.uniform(SIM_DAYS - 15, SIM_DAYS - 2)), "wire",
                   rng.choice(["ESTATE DISTRIBUTION", "SIGNING BONUS", "SALE PROCEEDS"]))

    # B9: name-screening near-miss: a long-standing customer whose name resembles a designee.
    b.person(name="Gregor Malenko", age=34, occupation="Pharmacist", tenure_days=2900)
    b.account(b.w.parties[-1])
    b.kyc_identity(b.w.parties[-1])

    # =================================================================================
    # Planted typologies (ground truth)
    # =================================================================================
    sanctioned = _sanctions_list(b)

    # ---- T1 STRUCTURING / SMURFING ----
    subj = b.person(name="Victor Hale", age=47, occupation="Independent Consultant", tenure_days=820)
    b.account(subj)
    b.kyc_identity(subj)
    subj["expected_monthly_inflow"] = 6000
    smurfs = []
    for i in range(5):
        s = b.person(age=rng.randint(21, 30), occupation=rng.choice(["Student", "Retail Associate", "Barista"]),
                     tenure_days=rng.randint(60, 400))
        b.account(s)
        b.kyc_identity(s)
        smurfs.append(s)
    used_branches = rng.sample(branches, 6)
    for k in range(4):  # four weekly rounds
        base = 24 + k * 15
        for i, s in enumerate(smurfs):
            day = base + rng.uniform(0, 2)
            amt = rng.uniform(9050, 9850)
            dep_ts = b.ts(day, 9, 16)
            b.cash_deposit(used_branches[i], b.primary(s), amt, dep_ts)
            b.transfer(b.primary(s), b.primary(subj), amt - rng.uniform(0, 150), b.after(dep_ts, 1, 20), "p2p", rng.choice(["", "repay", "for V"]))
        for j in range(2):
            b.cash_deposit(used_branches[(j + k) % 6], b.primary(subj), rng.uniform(9200, 9900), b.ts(base + j * 0.6, 10, 15))
    shell_xv = b.company(customer=False, name="Orion Trade Holdings Ltd", industry="General Trading", jurisdiction="XV", incorporated_days_ago=260)
    b.account(shell_xv, external=True, bank="Varnholm Private Bank", country="XV")
    for k in range(3):
        b.transfer(b.primary(subj), b.primary(shell_xv), rng.uniform(64_000, 72_000), b.ts(32 + k * 15), "wire", "CONSULTING SERVICES")
    b.scenario("STRUCT-01", "STRUCTURING", "Smurfing ring feeding a consultant's account",
               [b.primary(subj)] + [b.primary(s) for s in smurfs], [subj["id"]] + [s["id"] for s in smurfs],
               "Five young customers deposit $9.0k-$9.9k cash at different branches and forward it the same day to "
               "Victor Hale, who also deposits just under $10k himself; proceeds are wired to a recently formed "
               "Varnholm trading company.")

    # ---- T2 MONEY MULE RING (recruited students, shared devices) ----
    recruiter_fp = "a91f03c7d4e2b8f6"   # same physical phone used to onboard mules at Beta CU
    collector_phone = "+1-312-555-0187"
    dev_a = b.device(fingerprint=recruiter_fp, os_name="Android 16")
    dev_b = b.device(os_name="Android 15")
    shared_ip = b.ip("203.0.113.77")
    flat = b.address(city="Brookfield", line="77 Canal St, Apt 4B")
    mules = []
    for i in range(7):
        m = b.person(age=rng.randint(19, 23), occupation="Student", tenure_days=rng.randint(18, 48), risk="low")
        b.account(m, opened_days_ago=None)
        b.w.link("USES", m["id"], dev_a if i < 4 else dev_b)
        b.w.link("LOGGED_IN_FROM", m["id"], shared_ip)
        b.w.link("HAS_PHONE", m["id"], b.phone())
        b.w.link("HAS_EMAIL", m["id"], b.email(m))
        b.w.link("LIVES_AT", m["id"], flat if i < 3 else b.address(city="Brookfield"))
        mules.append(m)
    collector = b.person(name="Ronan Pike", age=31, occupation="Self-employed", tenure_days=33)
    b.account(collector)
    b.w.link("USES", collector["id"], dev_a)
    b.w.link("LOGGED_IN_FROM", collector["id"], shared_ip)
    b.w.link("HAS_PHONE", collector["id"], b.phone(collector_phone))
    b.w.link("HAS_EMAIL", collector["id"], b.email(collector))
    b.w.link("LIVES_AT", collector["id"], b.address(city="Brookfield"))
    vasp = b.company(customer=False, name="CoinHarbor Exchange (fictional VASP)", industry="Virtual Asset Service Provider", jurisdiction="XQ")
    b.account(vasp, external=True, bank="CoinHarbor", country="XQ")
    victims = rng.sample([p for p in persons if p["age"] >= 64], 24)
    for v in victims:
        v["_victim"] = True
    for vi, v in enumerate(victims):
        m = mules[vi % len(mules)]
        for _ in range(rng.randint(1, 2)):
            day = rng.uniform(SIM_DAYS - 40, SIM_DAYS - 3)
            amt = round(rng.uniform(900, 4800), -1)
            in_ts = b.ts(day)
            b.transfer(b.primary(v), b.primary(m), amt, in_ts, rng.choice(["p2p", "wire"]),
                       rng.choice(["investment", "crypto opportunity", "for the account", "help as discussed"]))
            b.transfer(b.primary(m), b.primary(collector), amt * rng.uniform(0.9, 0.97), b.after(in_ts, 0.5, 14), "p2p", "")
    inbound = sum(t["amount"] for t in b.w.transfers if t["dst"] == b.primary(collector))
    for k in range(6):
        b.transfer(b.primary(collector), b.primary(vasp), inbound / 7, b.ts(SIM_DAYS - 36 + k * 6), "wire", "deposit")
    b.scenario("MULE-01", "MONEY_MULE", "Student mule ring cashing out scam victims via crypto",
               [b.primary(m) for m in mules] + [b.primary(collector)], [m["id"] for m in mules] + [collector["id"]],
               "Seven newly onboarded students share two phones, one IP and a flat; elderly customers send them "
               "'investment' payments that are forwarded within hours to Ronan Pike, who wires the pool to a "
               "crypto exchange. The recruiter's phone and Pike's number were reported by Beta Credit Union.")
    b.w.shared["mule_device_fp"] = recruiter_fp
    b.w.shared["collector_phone"] = collector_phone

    # ---- T3 SHELL CAROUSEL (circular flow through same-director shells) ----
    director = b.person(customer=False, name="Anton Lisowski", age=52, country="XV")
    reg_addr = b.address(city="Port Varn", country="XV", line="Suite 4, 12 Harbour Rd")
    shells = []
    for nm, ind in [("Lumen Advisory Group LLC", "Management Consulting"), ("Northgate Supply Partners LLC", "Wholesale"),
                    ("Quill & Cask Trading LLC", "Import/Export"), ("Basalt Media Ventures LLC", "Marketing")]:
        s = b.company(name=nm, industry=ind, incorporated_days_ago=rng.randint(120, 150), tenure_days=rng.randint(80, 110))
        b.account(s)
        b.w.link("REGISTERED_AT", s["id"], reg_addr)
        b.w.link("DIRECTOR_OF", director["id"], s["id"])
        b.w.link("OWNS", director["id"], s["id"], pct=100.0)
        b.w.link("USES", s["id"], b.device())
        b.w.link("HAS_EMAIL", s["id"], b.email(s))
        b.w.link("LOGGED_IN_FROM", s["id"], b.ip("198.51.100.23"))
        shells.append(s)
    for rnd in range(4):
        amt = rng.uniform(46_000, 52_000)
        day = 12 + rnd * 18
        for i in range(4):
            b.transfer(b.primary(shells[i]), b.primary(shells[(i + 1) % 4]), amt * (0.985 ** i), b.ts(day + i * 1.3), "wire",
                       rng.choice(["CONSULTING FEE", "SERVICES Q3", "INVOICE 1001", "MARKETING RETAINER"]))
    seed_in = b.company(customer=False, name="Atlas Maritime Freight", industry="Shipping", jurisdiction="XT")
    b.account(seed_in, external=True, bank="Tessaly Commercial Bank", country="XT")
    b.transfer(b.primary(seed_in), b.primary(shells[0]), 51_000, b.ts(10), "wire", "ADVANCE")
    b.scenario("CAROUSEL-01", "ROUND_TRIPPING", "Four same-director shells cycling funds",
               [b.primary(s) for s in shells], [s["id"] for s in shells] + [director["id"]],
               "Four LLCs formed within a month share a Varnholm registered address and a single director; "
               "they pass roughly $50k around a closed loop four times, generating fake turnover.")

    # ---- T4 SANCTIONS EXPOSURE via aggregated ownership (OFAC 50% rule) ----
    bluefin = b.company(name="Bluefin Marine Imports LLC", industry="Marine Equipment Import", tenure_days=1400)
    b.account(bluefin)
    b.kyc_identity(bluefin)
    bluefin["expected_activity"] = "Imports marine equipment; supplier wires $20k-$90k."
    aurora = b.company(customer=False, name="Aurora Maritime Components Ltd", industry="Marine Equipment", jurisdiction="XT", incorporated_days_ago=700)
    coral = b.company(customer=False, name="Coral Freight Logistics Ltd", industry="Freight", jurisdiction="XT", incorporated_days_ago=1500)
    northstar = b.company(customer=False, name="Northstar Holdings SA", industry="Holding Company", jurisdiction="XV", incorporated_days_ago=2000)
    b.account(aurora, external=True, bank="Tessaly Commercial Bank", country="XT")
    b.account(coral, external=True, bank="Tessaly Commercial Bank", country="XT")
    b.w.link("OWNS", sanctioned["malenko"], aurora["id"], pct=30.0)
    b.w.link("OWNS", northstar["id"], aurora["id"], pct=25.0)
    b.w.link("OWNS", sanctioned["selene"], northstar["id"], pct=100.0)
    b.w.link("OWNS", b.person(customer=False, name="Ilse Brandt", age=58, country="DE")["id"], aurora["id"], pct=45.0)
    b.w.link("OWNS", sanctioned["malenko"], coral["id"], pct=40.0)
    b.w.link("OWNS", b.person(customer=False, name="Tomas Ferreira", age=49, country="XT")["id"], coral["id"], pct=60.0)
    for m in range(3):
        b.transfer(b.primary(bluefin), b.primary(aurora), rng.uniform(62_000, 88_000), b.ts(20 + m * 25), "wire", f"PO AMC-{7700 + m}")
        b.transfer(b.primary(bluefin), b.primary(coral), rng.uniform(9_000, 14_000), b.ts(22 + m * 25), "wire", "FREIGHT")
        for _ in range(5):
            b.transfer(b.primary(rng.choice(merchants[7:9])), b.primary(bluefin), rng.uniform(12_000, 26_000), b.ts(m * 30 + rng.uniform(0, 29)), "ach", "RECEIPT")
    b.scenario("SANCT-01", "SANCTIONS_EVASION", "Supplier blocked under the 50% rule via layered ownership",
               [b.primary(bluefin)], [bluefin["id"], aurora["id"]],
               "Bluefin pays Aurora Maritime, which is not listed itself but is 30% owned by designated Grigor "
               "Malenko and 25% by Northstar Holdings, wholly owned by designated Selene Group: 55% aggregate "
               "blocked ownership. Coral Freight (40%) is below the threshold but warrants enhanced due diligence.")

    # ---- T5 RAPID LAYERING (fan-out / fan-in across new accounts) ----
    halcyon = b.company(name="Halcyon Strategic Consulting LLC", industry="Consulting", incorporated_days_ago=95, tenure_days=41)
    b.account(halcyon)
    b.kyc_identity(halcyon)
    halcyon["expected_activity"] = "Start-up consultancy; expected monthly volume under $25k."
    origin = b.company(customer=False, name="Qastria Development Fund", industry="Investment Fund", jurisdiction="XQ")
    b.account(origin, external=True, bank="Qastria National Bank", country="XQ")
    hops = []
    for _ in range(3):
        h = b.person(age=rng.randint(26, 44), occupation=rng.choice(["Consultant", "Self-employed", "Sales Agent"]), tenure_days=rng.randint(35, 70))
        b.account(h)
        b.kyc_identity(h)
        hops.append(h)
    ends = []
    for nm in ["Varn Capital Nominees", "Blue Lantern Trust Co"]:
        e = b.company(customer=False, name=nm, industry="Trust Services", jurisdiction="XV")
        b.account(e, external=True, bank="Varnholm Private Bank", country="XV")
        ends.append(e)
    for wave in range(2):
        day = SIM_DAYS - 25 + wave * 9
        amount = rng.uniform(175_000, 195_000)
        in_ts = b.ts(day, 9, 11)
        b.transfer(b.primary(origin), b.primary(halcyon), amount, in_ts, "wire", "SEED INVESTMENT")
        for i, h in enumerate(hops):
            part = amount * 0.97 / 3
            t1 = b.after(in_ts, 1 + i * 0.5, 3 + i * 0.5)
            b.transfer(b.primary(halcyon), b.primary(h), part, t1, "wire", "SUBCONTRACTOR FEE")
            for j, e in enumerate(ends):
                b.transfer(b.primary(h), b.primary(e), part * 0.96 / 2, b.after(t1, 6 + j * 3, 20 + j * 3), "wire", "ADVISORY")
    b.scenario("LAYER-01", "LAYERING", "Seed 'investment' split across new accounts and parked offshore",
               [b.primary(halcyon)] + [b.primary(h) for h in hops], [halcyon["id"]] + [h["id"] for h in hops],
               "A six-week-old consultancy receives two ~$185k wires from a Qastria fund, splits each across "
               "three newly opened individual accounts within hours, and they forward ~96% to two Varnholm "
               "trust companies the next day.")

    _history_alpha(b, payroll, mart)
    return b.w


def _sanctions_list(b: Builder) -> dict[str, str]:
    """Synthetic designations (OFAC-style), loaded into every bank's graph as reference data."""
    entries = {
        "malenko": b.person(customer=False, name="Grigor Malenko", age=61, country="XV",
                            sanctioned=True, program="SYN-TCO", list_id="SYN-SDN-1043"),
        "selene": b.company(customer=False, name="Selene Group Holdings", industry="Holding Company",
                            jurisdiction="XV", sanctioned=True, program="SYN-TCO", list_id="SYN-SDN-1044"),
        "drago": b.person(customer=False, name="Dragan Voskresenko", age=55, country="XQ",
                          sanctioned=True, program="SYN-CYBER", list_id="SYN-SDN-2210"),
        "hydra": b.company(customer=False, name="Hydra Bay Shipping Co", industry="Shipping",
                           jurisdiction="XQ", sanctioned=True, program="SYN-NPWMD", list_id="SYN-SDN-3302"),
    }
    return {k: v["id"] for k, v in entries.items()}


def _history_alpha(b: Builder, payroll: dict, mart: dict) -> None:
    """Prior, already-closed cases: the episodic memory Hound starts with."""
    b.w.history["cases"] = [
        {"id": "CASE-2026-0007", "opened": SIM_END - 70 * DAY, "closed": SIM_END - 66 * DAY,
         "status": "CLOSED", "disposition": "FALSE_POSITIVE", "typologies": ["FAN_OUT"],
         "subjects": [payroll["id"]], "accounts": [b.primary(payroll)],
         "summary": "Fan-out alert on Brightline Payroll Services. Verified as a licensed payroll processor; "
                    "outbound ACH batches match client funding received the prior day.",
         "analyst": "j.okafor",
         "lesson": "Payroll processors fan out to hundreds of employees by design. Check that each batch is "
                   "pre-funded by client ACH credits before escalating fan-out alerts."},
        {"id": "CASE-2026-0011", "opened": SIM_END - 52 * DAY, "closed": SIM_END - 49 * DAY,
         "status": "CLOSED", "disposition": "FALSE_POSITIVE", "typologies": ["STRUCTURING"],
         "subjects": [mart["id"]], "accounts": [b.primary(mart)],
         "summary": "Cash structuring alert on Sunrise Mini Mart. Deposits range $1.8k-$14.5k with regular "
                    "CTR filings; amounts do not cluster under $10k. Consistent with a cash-intensive store.",
         "analyst": "m.reyes",
         "lesson": "A customer who routinely deposits over $10,000 (triggering CTRs) is not avoiding the "
                   "threshold. Compare the share of deposits in the $8k-$10k band with deposits above $10k."},
    ]
    b.w.history["playbook_lessons"] = {
        "STRUCTURING": "Look for linked depositors (smurfs): other customers who deposit cash and forward it to "
                       "the subject the same day. Multiple branches within 48 hours strengthens the case.",
        "MONEY_MULE": "New accounts that share a device or IP with other new accounts and forward >90% of "
                      "inbound funds within 24 hours are the strongest mule signal. Check the consortium.",
    }


# =====================================================================================
# Beta Credit Union: smaller, already caught part of the same mule operation.
# =====================================================================================

def build_beta(alpha_shared: dict, seed: int = 11) -> World:
    b = Builder("beta", seed, "Beta Credit Union", "091000777")
    rng = b.rng
    branches = b.branches(4)
    employers = [b.company(customer=False, industry="Employer") for _ in range(12)]
    merchants = [b.company(customer=False, industry=i) for i in ["Grocery", "Fuel", "Card Settlement", "Restaurants"]]
    landlords = [b.company(customer=False, industry="Property Management") for _ in range(5)]
    for c in employers + merchants + landlords:
        b.account(c, external=True, bank="Summit National")
    persons = []
    for _ in range(320):
        p = b.person()
        b.account(p)
        b.kyc_identity(p)
        persons.append(p)
        pay = p["_pay"] or 2200
        for d in range(rng.randint(0, 13), SIM_DAYS, 14):
            b.transfer(b.primary(rng.choice(employers)), b.primary(p), pay * rng.uniform(0.97, 1.03), b.ts(d, 1, 5), "ach", "PAYROLL")
        for m in range(3):
            b.transfer(b.primary(p), b.primary(rng.choice(landlords)), round(pay * 0.6, -1), b.ts(m * 30 + 1), "ach", "RENT")
        for wk in range(0, SIM_DAYS, 7):
            b.transfer(b.primary(p), b.primary(rng.choice(merchants)), rng.uniform(40, 300), b.ts(wk + rng.randint(0, 6)), "card", "CARD")
    for _ in range(900):
        a, c = rng.sample(persons, 2)
        b.transfer(b.primary(a), b.primary(c), rng.choice([20, 40, 60, 100, 150]), b.ts(rng.uniform(0, 89)), "p2p", "")
    _sanctions_list(b)

    # The earlier wave of the same mule operation, caught and reported in September.
    dev = b.device(fingerprint=alpha_shared["mule_device_fp"], os_name="Android 16")
    early_mules = []
    for i in range(3):
        m = b.person(age=rng.randint(19, 22), occupation="Student", tenure_days=rng.randint(80, 110))
        b.account(m)
        b.w.link("USES", m["id"], dev)
        b.w.link("LOGGED_IN_FROM", m["id"], b.ip("203.0.113.77"))
        b.w.link("HAS_PHONE", m["id"], b.phone(alpha_shared["collector_phone"]) if i == 0 else b.phone())
        b.w.link("HAS_EMAIL", m["id"], b.email(m))
        b.w.link("LIVES_AT", m["id"], b.address(city="Brookfield"))
        early_mules.append(m)
    vasp = b.company(customer=False, name="CoinHarbor Exchange (fictional VASP)", industry="Virtual Asset Service Provider", jurisdiction="XQ")
    b.account(vasp, external=True, bank="CoinHarbor", country="XQ")
    for v in rng.sample([p for p in persons if p["age"] >= 60], 8):
        m = rng.choice(early_mules)
        day = rng.uniform(5, 30)
        amt = rng.uniform(1200, 4000)
        in_ts = b.ts(day)
        b.transfer(b.primary(v), b.primary(m), amt, in_ts, "p2p", "investment")
        b.transfer(b.primary(m), b.primary(vasp), amt * 0.95, b.after(in_ts, 2, 10), "wire", "deposit")
    for m in early_mules:
        for a in b.w.accounts:
            if a["owner"] == m["id"]:
                a["status"] = "closed"
    b.w.history["cases"] = [{
        "id": "CASE-B-2026-0031", "opened": SIM_END - 48 * DAY, "closed": SIM_END - 41 * DAY,
        "status": "CLOSED", "disposition": "SAR_FILED", "typologies": ["MONEY_MULE"],
        "subjects": [m["id"] for m in early_mules], "accounts": [b.primary(m) for m in early_mules],
        "summary": "Three student accounts onboarded from one Android device received elder-fraud proceeds and "
                   "wired them to CoinHarbor. Accounts exited; SAR filed; identifiers shared via 314(b).",
        "analyst": "k.lindqvist",
        "lesson": "This crew recruits students near Brookfield and onboards them from the same handset.",
        "publish": [{"kind": "device", "value": alpha_shared["mule_device_fp"]},
                    {"kind": "phone", "value": alpha_shared["collector_phone"]},
                    {"kind": "ip", "value": "203.0.113.77"}],
    }]
    b.scenario("MULE-B-EARLY", "MONEY_MULE", "Earlier wave of the same mule crew (already exited)",
               [b.primary(m) for m in early_mules], [m["id"] for m in early_mules],
               "Closed in September; included so cross-bank links have a source.")
    return b.w


def build_worlds() -> dict[str, World]:
    alpha = build_alpha()
    beta = build_beta(alpha.shared)
    return {"alpha": alpha, "beta": beta}
