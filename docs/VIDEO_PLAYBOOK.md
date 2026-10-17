# Video playbook: from zero to submitted

Goal: one 3-minute video that makes a judge think "this person knows AML, the graph does real work, and it actually runs."
Judges check: does the graph shape what the agent does? Can it remember across sessions? Can it show the path behind each answer? Does it work?

---

## 0. The shape of the video (memorise this)

| Part | Time | On screen | Purpose |
|---|---|---|---|
| A. Hook | 0:00-0:20 | **You on camera** (or slide 1) | Why this problem matters, why you |
| B. The idea | 0:20-0:35 | Slide 2 (one diagram) | Graph = data + memory + evidence |
| C. Live demo | 0:35-2:35 | **The live site** | Show, don't tell |
| D. Proof | 2:35-2:50 | Benchmark tab | Numbers |
| E. Close | 2:50-3:00 | You on camera / slide 4 | One memorable line |

No code walkthrough in the video. Code is in the repo; judges open it themselves. Show **one** Cypher query inside the app (the Evidence tab), that is enough.

---

## 1. Prepare (30 min, the day you record)

**Gear**
- Screen recorder: **OBS Studio** (free, obsproject.com). Alternative: Windows **Win + Alt + R** (Xbox Game Bar), or Clipchamp's screen+camera recorder.
- Mic: wired earphones with a mic are better than the laptop mic. Quiet room, fan off.
- Camera (optional but recommended): laptop webcam for the intro/outro, eye level, light in front of you (window or lamp behind the laptop), plain background.

**OBS setup (5 min)**
1. Settings → Video: Base and Output **1920x1080**, 30 fps. Settings → Output: Recording format **mp4**.
2. Scene "Demo": add **Display Capture** (your screen) + **Audio Input Capture** (your mic).
   Optional: add **Video Capture Device** (webcam), resize to a small circle/box in the bottom-right corner.
3. Scene "Face": webcam full screen + mic (for the hook and close).
4. Do a 10-second test recording and listen to it.

**Browser**
- Chrome, a clean profile or guest window (no bookmarks bar, no extensions), zoom **110%**, full screen **F11**.
- Tab 1: https://hound-99l2.onrender.com
- Tab 2: https://github.com/manav-Mnv/hound-aml (for the last 3 seconds, optional)
- Tab 3: your slides (Google Slides in present mode)
- Close WhatsApp/Slack/notifications (Windows: **Focus assist / Do not disturb** on).

**App**
1. Run `python scripts/server_hell.py` 10 minutes before so Render is awake.
2. In the app click **Reset** (top right). Wait until the alert queue shows **Open 71**.
3. Do one full dry run of section 3 without recording (5 min). Then click **Reset** again.

---

## 2. The slides (4 slides, Google Slides, 15 min)

Dark background, big text, no paragraphs.

1. **Title** — "Hound" · *AML agents that follow the money, remember every case, and show their work* · Graph Hacks 2026 · Tracks 01 + 02 · your name.
2. **The problem** — big number "**~95%** of AML alerts are false positives" (NICE Actimize survey) · "4.7M SARs filed in FY2024 (FinCEN)" · "TD Bank: ~$3B penalty, 2024".
3. **The idea** — one diagram: `Transactions + Identities + Ownership` and `Cases + Lessons + Evidence` → **one FalkorDB graph** → `Triage → Investigator → SAR writer → Reviewer → Human`. Under it: "One FalkorDB, three isolated graphs: Bank A, Bank B, Consortium (hashes only)".
4. **Results** — "71 alerts → 49 cases · 41/41 false positives closed with reasons · 5/5 schemes caught · 0 false SARs · 5 accounts no rule flagged" + repo URL + live URL.

---

## 3. Shot-by-shot script (what to do, what to say)

Speak slowly. Say it in your own words; the lines below are a guide. Pause 1 second before each click.

### A. Hook — 0:00-0:20 (Scene "Face", or slide 1)
> "Hi, I'm Manav. I work with anti-money-laundering. Banks run thousands of rules on transactions, and about 95 percent of the alerts they raise are false positives. Analysts spend their day joining accounts, phones and old cases by hand. I built Hound to put all of that into one FalkorDB graph and let agents follow the money."

### B. The idea — 0:20-0:35 (slide 3)
> "Everything lives in one graph: the transactions, the identities, company ownership, and the agents' own memory — past cases, analyst lessons, and every piece of evidence with the Cypher query that produced it. Four agents hand work to each other through that graph, and a human makes the final call."

### C1. The alert landscape — 0:35-0:50 (switch to Scene "Demo", site, Investigate tab)
- Do: nothing yet, let the landscape graph sit for 2 seconds. Hover over a big red node.
> "This is Alpha Bank: synthetic data, 71 alerts from six ordinary threshold rules. The triage agent already scored every alert from the graph — shared devices, brand-new accounts, links to other alerts — in under a second. Bigger and redder means riskier, and you can already see clusters."

### C2. The mule ring — 0:50-1:35
- Do: click **Whitney Walker** (top of the queue) → **Investigate with Hound**.
> "Let's give the top alert to the investigator. It starts by reading its playbook and lessons from the graph, then every step is a Cypher query."
- Do: watch the graph grow. When the identity cluster appears, point with the mouse.
> "Two phones and one IP shared by eight brand-new customers — that's FalkorDB's WCC algorithm finding the ring. Ninety-five percent of the money leaves within hours, to Ronan Pike, and from him to a crypto exchange offshore."
- Do: when the consortium hit appears in the trace, hover it.
> "And here's the part I'm proud of: Beta Credit Union reported this exact phone in September. Two banks, two isolated graphs in the same FalkorDB — they only share hashed identifiers, never customer data, like FinCEN's 314(b) program."
- Do: click **Money flow** (top right of the graph).
> "Same evidence as a money trail: victims on the left, mules in the middle, the cash-out on the right. It also merged the other seven alerts into this one case, so no two analysts work the same ring."

### C3. Show its work — 1:35-2:00
- Do: open the **SAR** tab. Click one yellow citation chip.
> "It drafts the SAR in FinCEN's who-what-when-where-why format. Every sentence cites evidence — click it, and here's the exact Cypher query that ran on FalkorDB. A reviewer agent checks every dollar amount against the evidence; if the writer invents a number, it's sent back."
- Do: type a short note in the analyst box, e.g. "Recruiter crew near Brookfield", click **Approve & file SAR**.
> "I approve it. The note becomes a lesson in memory, and the hashed identifiers go to the consortium for the next bank."

### C4. A false positive, closed with memory — 2:00-2:20
- Do: click **Reset** is NOT needed. In the queue search box type `Brightline`, select it, **Investigate with Hound**.
> "Now the boring alert that eats analyst time: a payroll company paying 160 people. Rules panic every two weeks. Hound recalls the lesson an analyst attached to this company in August, checks the payroll is pre-funded, and closes it — with the reason written down and cited."

### C5. Sanctions the rule missed — 2:20-2:35
- Do: search `Bluefin`, select, **Investigate with Hound**, open **Findings**.
> "This alert fired for a high-risk country. The graph found the real issue: the supplier is 30 percent owned by a sanctioned person and 25 percent by a holding company that is itself owned by another. Fifty-five percent in aggregate — blocked under OFAC's 50 percent rule, even though it's on no list."

### D. Proof — 2:35-2:50 (Benchmark tab, then Memory tab for 3 seconds)
> "On the full queue: all 41 false positives closed with reasons, all five laundering schemes escalated, zero false SARs, and five accounts no rule ever flagged. And this is the memory graph — cases, lessons, playbooks and agent runs, all in FalkorDB."

### E. Close — 2:50-3:00 (Scene "Face" or slide 4)
> "Hound follows the money, remembers every case, and shows its work. It's open source, it's live, and the link is below. Thank you."

**If something goes wrong while recording:** keep going if it's small; otherwise stop, click **Reset** (or open another alert) and record that part again. You'll stitch the parts together.

**Backup trick:** after an investigation finishes, the **Replay investigation** button replays it step by step — handy if you missed the moment.

---

## 4. Edit (30 min) — Clipchamp (built into Windows) or CapCut

1. Import all clips, put them in order, cut dead air and "umm"s.
2. Add slide images where the script says (or record the slides as video).
3. Add small text labels when it helps: "WCC finds the ring", "Consortium hit (hashed)", "OFAC 50% rule".
4. Optional: soft background music at 10% volume.
5. Keep it **≤ 3:00** (3:30 absolute max). Export **1080p mp4**.

---

## 5. Upload (10 min)

YouTube → Create → Upload.
- Title: `Hound – AML investigation agents on FalkorDB | Graph Hacks 2026`
- Description:
  ```
  Hound follows the money through a FalkorDB graph, remembers every case, and writes SARs where every sentence cites the Cypher query behind it.
  Live demo: https://hound-99l2.onrender.com
  Code: https://github.com/manav-Mnv/hound-aml
  Tracks: 01 Agents That Act on Connected Data, 02 Agent Memory and Coordination. All data is synthetic.
  ```
- Visibility: **Unlisted** (or Public). Copy the link.

Then send the link here so it goes into the README.

---

## 6. Blog (30 min, AirPods side prize)

Hashnode or Dev.to → new post → paste `docs/BLOG.md` → add 3 screenshots (landscape graph, mule ring with consortium hit, SAR with citations) → embed the YouTube video → tags: `falkordb`, `graph-database`, `ai-agents`, `aml`. Publish, copy the link.

---

## 7. The submission form (WeMakeDevs)

- **Project name:** Hound
- **One-liner:** AML investigation agents that follow the money through FalkorDB, remember every case, and write SARs where every sentence cites a Cypher query.
- **Repository:** https://github.com/manav-Mnv/hound-aml
- **Live deployment:** https://hound-99l2.onrender.com (free tier; first load after idle can take a minute)
- **Demo video:** your YouTube link
- **Tracks:** Track 01 – Agents That Act on Connected Data; Track 02 – Agent Memory and Coordination
- **How FalkorDB is used:** one instance, three isolated graphs (two banks + a hashed consortium); multi-hop time-ordered Cypher, WCC / PageRank / betweenness / label propagation as agent tools, OFAC 50% ownership aggregation, memory (cases, lessons, playbooks, evidence) stored as nodes linked to the entities; reads through GRAPH.RO_QUERY.
- **AI assistance:** "An AI coding assistant was used during development; all code was reviewed, run and tested by me."
- **Blog:** your post link

Submit at least 3 hours before 18 Oct, 11:59 PM IST.

---

## 8. Be ready for judge questions (practise out loud)

- **Why a graph?** The questions are about connections: who shares this phone, where did the money go, who owns this supplier, have we seen this before. Each is one traversal instead of many joins.
- **Where is the memory?** Cases, findings, evidence, lessons and playbooks are nodes in the same graph, linked to the accounts and people they're about. Recall is a traversal; it persists across sessions because it's in FalkorDB.
- **How do agents coordinate?** Each agent run is an `AgentRun` node with `HANDOFF` edges; they share the case node. Open cases de-duplicate new alerts on the same ring.
- **How is it explainable?** Every tool call is an `Evidence` node storing the exact Cypher; findings and SAR sentences must cite evidence ids; the reviewer rejects amounts not in the cited evidence.
- **OFAC 50% rule?** Walk ownership edges up to 4 hops; an entity is blocked when blocked owners hold ≥50% in aggregate; repeat until nothing changes (so blocked holding companies count).
- **Cross-bank without sharing data?** Only HMAC hashes of identifiers go to the consortium graph; a match tells you "another member reported this phone", nothing else. Production would use private set intersection.
- **Why so few false positives in your data?** It's synthetic and deliberately rich in schemes so every typology is exercised; real life is ~95% false positives.
- **Does it need an LLM?** No. With an Anthropic key the investigator and SAR writer run on Claude; without one, a deterministic playbook runner uses the same tools and memory. The benchmark numbers are from the offline mode, so anyone can reproduce them.
