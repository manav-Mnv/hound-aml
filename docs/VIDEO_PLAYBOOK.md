# Video playbook (final): 3 minutes, deck + live site

Judges ask: does the graph shape what the agent does? Does it remember? Can it show the path behind each answer? Does it actually run?
The video answers all four in this order: **problem → idea → live proof → numbers**.

---

## 0. Deck fixes before you record (5 min)

| Slide | Change | Why |
|---|---|---|
| 1 Title | Add a line: `Live: hound-99l2.onrender.com` | Judges can click it straight from the video |
| 3 Why a graph | `( Person )-[:OWNS*1..4]->( Company )` → `( Party )-[:OWNS*1..4]->( Company )` | Owners can be companies too (Northstar owns Aurora) |
| 8 Memory | Add one line: `8 alerts on one ring → merged into 1 case` | Shows agent coordination (Track 02) with a number |
| 9 Results | Footnote: `Synthetic benchmark · ground truth kept outside the graph · reproduce: uv run hound eval` | Pre-empts the "is this real?" question honestly |

Everything else (95%, 4.7M, ~$3B, 71→49, 41/41, 5/5, 0, +5, the OFAC 55%) matches the code and the sources.

---

## 1. Prepare (30 min)

- **Record with** OBS Studio (free): 1920x1080, 30 fps, mp4. Scene **Face** = webcam + mic; scene **Screen** = display capture + mic + small webcam circle bottom-right (optional).
- **Mic**: wired earphones, quiet room. Turn on Windows **Do not disturb**.
- **Chrome** (guest window, no extensions): tab 1 = the deck in present mode, tab 2 = https://hound-99l2.onrender.com at zoom 110% and full screen (F11).
- **Wake the site**: run `python scripts/server_hell.py` 10 minutes before.
- **Fresh state**: in the app click **Reset** (top right) and wait until the queue shows **Open 71** and the landscape graph appears.
- **Dry run** section 3 once without recording, then **Reset** again.

---

## 2. Timeline

| Time | Screen | Slide / site |
|---|---|---|
| 0:00-0:12 | Face | — |
| 0:12-0:25 | Deck | Slide 2 (problem) |
| 0:25-0:40 | Deck | Slide 4 (architecture) |
| 0:40-2:30 | **Live site** | Investigate → SAR → memory → sanctions |
| 2:30-2:45 | Live site | Benchmark tab |
| 2:45-3:00 | Deck / Face | Slide 9 |

Slides 3, 5, 6, 7 and 8 stay in the deck for judges and the viva; don't spend video time on them. The live site shows the same things working.

---

## 3. Shot-by-shot (do / say)

Speak slowly, your own words. Pause one beat before each click.

**0:00 Face**
> "Hi, I'm Manav, and I work in anti-money-laundering. Banks raise thousands of alerts a day, and about 95 percent of them are false positives. I built Hound to fix that with a graph."

**0:12 Slide 2**
> "Almost 95 percent false positives, 4.7 million SARs a year in the US alone, and when banks get it wrong it costs billions, like TD Bank's three-billion-dollar penalty. The real problem is that analysts join accounts, phones and old cases by hand."

**0:25 Slide 4**
> "Hound puts everything into FalkorDB: transactions, identities, company ownership, and the agents' own memory. Four agents (triage, investigator, SAR writer and reviewer) work through that graph, and a human makes the final call. Two banks live in isolated graphs; a third graph holds only hashed signals they share."

**0:40 Site, Investigate tab, landscape visible**
- Do: hover a big red node for a second.
> "This is a synthetic bank with 71 alerts from six ordinary rules. The triage agent scored every one from graph features in under a second. Bigger and redder is riskier, and you can already see the rings."

**0:55 The mule ring**
- Do: click **Whitney Walker** (top of the queue) → **Investigate with Hound**.
> "I hand the top alert to the investigator. It reads its playbook and past lessons from the graph, and every step it takes is a Cypher query."
- Do: as the graph grows, point at the shared phones/IP cluster.
> "Eight brand-new customers sharing two phones and one IP: FalkorDB's WCC algorithm found the ring. Ninety-five percent of the money leaves within hours, to Ronan Pike, then to a crypto exchange offshore."
- Do: point at the consortium signal in the trace.
> "And here's the key moment: Beta Credit Union reported this same phone in September. The banks never shared customer data, only hashes, like FinCEN's 314(b) program."
- Do: click **Money flow** (top right of the graph).
> "Same evidence as a money trail: victims on the left, mules in the middle, cash-out on the right. It also merged the other seven alerts into this one case."

**1:40 Shows its work**
- Do: open the **SAR** tab → click one yellow citation chip → the **Evidence** tab opens.
> "The SAR follows FinCEN's who, what, when, where, why. Every sentence cites evidence, and this is the exact Cypher that ran. A reviewer agent rejects any dollar amount that isn't in the cited evidence."
- Do: type `Recruiter crew near Brookfield` in the note box → **Approve & file SAR**.
> "I approve it. My note becomes a lesson in memory, and the hashed identifiers go to the consortium."

**2:05 False positive, closed from memory**
- Do: search box → `Brightline` → select → **Investigate with Hound** → **Findings** tab.
> "Now the alert that wastes analyst time: a payroll company paying 160 people. Hound recalls the lesson an analyst attached to this company in August, checks the payroll is pre-funded, and closes it with a written, cited reason."

**2:18 Sanctions the rule missed**
- Do: search `Bluefin` → select → **Investigate with Hound** → **Findings**.
> "This one fired for a high-risk country. The graph found the real problem: the supplier is 55 percent owned by sanctioned parties through a holding company. That makes it blocked under OFAC's 50 percent rule, even though it's on no list."

**2:30 Benchmark tab**
> "Across the whole queue: 41 of 41 false positives closed with reasons, five of five laundering schemes caught, zero false SARs, and five accounts no rule ever flagged."

**2:45 Slide 9 / Face**
> "Hound follows the money, remembers every case and shows its work. It's live and open source; links below. Thank you."

**If the live site is slow**: an investigation takes 5-15 seconds on the free server, so keep talking while it runs. If you miss a moment, the **Replay investigation** button replays the last investigation step by step.

**If you're asked about the AI**: the live demo runs the deterministic playbook mode (the pill at the top says "Offline playbook mode"). With an Anthropic key the investigator and SAR writer run on Claude with the same tools and memory. The benchmark uses the deterministic mode so anyone can reproduce it.

---

## 4. Edit, upload, blog

- **Edit** in Clipchamp or CapCut: trim pauses, add small captions ("WCC finds the ring", "Consortium hit", "OFAC 50% rule"), keep it **≤ 3:00**, export 1080p mp4.
- **YouTube**: title `Hound – AML investigation agents on FalkorDB | Graph Hacks 2026`, Unlisted. Description:
  ```
  Hound follows the money through a FalkorDB graph, remembers every case, and writes SARs where every sentence cites the Cypher query behind it.
  Live: https://hound-99l2.onrender.com
  Code: https://github.com/manav-Mnv/hound-aml
  Tracks 01 + 02. All data is synthetic.
  ```
- **Blog** (AirPods prize): Hashnode or Dev.to, paste `docs/BLOG.md`, add 3 screenshots (landscape, mule ring with consortium hit, SAR with citations) and the YouTube embed.
- Export the deck as **PDF** too, and attach it if the form allows.

---

## 5. Submission form (WeMakeDevs)

- **Name:** Hound
- **One-liner:** AML investigation agents that follow the money through FalkorDB, remember every case, and write SARs where every sentence cites a Cypher query.
- **Repo:** https://github.com/manav-Mnv/hound-aml
- **Live:** https://hound-99l2.onrender.com (free tier; first load after idle can take a minute)
- **Video:** your YouTube link
- **Tracks:** 01 Agents That Act on Connected Data · 02 Agent Memory and Coordination
- **How FalkorDB is used:** one instance with three isolated graphs (two banks + a hashed consortium); time-ordered multi-hop Cypher; WCC, PageRank, betweenness and label propagation as agent tools; OFAC 50% ownership aggregation; memory (cases, lessons, playbooks, evidence) stored as nodes linked to the entities; model reads through GRAPH.RO_QUERY.
- **AI assistance:** "An AI coding assistant was used during development; all code was reviewed, run and tested by me."

Submit at least 3 hours before **18 Oct, 11:59 PM IST**.

---

## 6. Viva answers (practise out loud)

- **Why a graph?** Every investigator question is about connections. Each one is a single traversal instead of many joins.
- **Where is the memory?** Cases, findings, evidence, lessons and playbooks are nodes linked to the same people and accounts as the transactions. Recall is a traversal, and it persists because it lives in FalkorDB.
- **How do agents coordinate?** Each run is an `AgentRun` node with `HANDOFF` edges, all attached to the shared case. Open cases absorb new alerts on the same ring.
- **How is it explainable?** Every tool call is an `Evidence` node holding its Cypher. Findings and SAR sentences must cite evidence ids, and the reviewer rejects amounts not found in that evidence.
- **The OFAC algorithm?** Walk `OWNS` edges up to 4 hops. An entity is blocked when blocked owners hold 50% or more in aggregate. Repeat until nothing changes, so blocked holding companies count too.
- **Cross-bank privacy?** Only HMAC hashes go to the consortium graph. A match says "another member reported this phone" and nothing more. Production would use private set intersection.
- **Why are your numbers so good?** The data is synthetic and deliberately rich in schemes so every typology is exercised; real life is about 95% false positives. Ground truth sits outside the graph, so the agents can't see it.
- **Does it need an LLM?** No. Claude runs the investigator and SAR writer when a key is set; the deterministic mode uses the same tools and memory.
