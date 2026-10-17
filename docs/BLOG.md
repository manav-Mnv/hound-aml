# Teaching an AML agent to follow the money with FalkorDB

*Graph Hacks 2026 entry: Hound. Tracks 01 and 02.*

Anti-money-laundering teams have a strange job. Software flags millions of transactions; humans then spend most of their day proving that the software was wrong. Industry surveys put 90-95% of transaction-monitoring alerts as false positives. The rest matter a lot: in 2024 TD Bank paid about $3 billion after laundering networks moved hundreds of millions through accounts nobody was watching.

What makes an alert real or not is almost never in the alert. It's in the connections: who else logs in from this phone, where the money went next, who ultimately owns this supplier, whether a colleague already cleared this customer last month. That is a graph problem, so we built Hound on one.

## One graph for data, memory and evidence

Hound loads two synthetic banks into FalkorDB as two isolated graphs (`hound:alpha`, `hound:beta`) in a single instance, plus a third graph, `hound:consortium`, that holds nothing but keyed hashes of risky identifiers. Customers, accounts, devices, IPs, phones, addresses, companies and ownership stakes are nodes; transfers and cash deposits are relationships with amounts and timestamps.

The important decision was to put the agent's memory in the same graph. A case is a node linked to the parties and accounts it concerns. Every tool call becomes an `(:Evidence)` node storing the exact Cypher and parameters, linked to the entities it touched. Findings link to evidence; SARs cite evidence; analyst lessons hang off the customers they are about and off typology playbooks. "Have we seen this before?" stops being a search problem and becomes a two-hop traversal.

## Agents that use the graph to decide

Six threshold rules (written in Cypher) produce 71 alerts. A triage agent scores all of them in about 200 ms from graph features (WCC identity clusters, PageRank, new accounts, prior false-positive cases, consortium hits) and groups alerts that belong to the same ring with a union-find over shared identifiers and money links: 71 alerts become 43 candidate cases.

The investigator (Claude Opus 5.5) gets 17 tools. Some are multi-hop Cypher (time-ordered money trails, loops back to the origin, linked cash depositors), some are FalkorDB algorithms (`algo.WCC`, `algo.pageRank`, `algo.betweenness`, `algo.labelPropagation`), and one lets it write its own read-only Cypher, executed through `GRAPH.RO_QUERY` so the database itself refuses writes. Its first call is always memory: the playbook for the typology and the lessons analysts attached to it.

Three moments from the demo show why the graph matters:

- **A mule ring.** A student's account forwards 95% of what it receives within hours. WCC over devices and IPs shows eight new customers sharing two phones; the trail ends at a crypto exchange; and a hash of the recruiter's phone matches what Beta Credit Union reported in September. Alpha never sees Beta's customers, only the match.
- **A false positive that stays closed.** A payroll processor fans out to 160 people every two weeks. The rule fires every time. Hound recalls the lesson an analyst attached to that company in August, checks that each batch was pre-funded, and closes the alert with a cited reason.
- **A sanctions problem the rule didn't see.** A wire to a high-risk jurisdiction turns out to pay a supplier that is 30% owned by a designated person and 25% by a holding company that is itself wholly owned by another designee. 55% in aggregate: blocked under OFAC's 50% rule even though it appears on no list. That's a four-hop ownership traversal plus a fixed point, trivial in a graph and painful anywhere else.

## Showing the work

A SAR is only useful if an examiner can trust it. Hound's SAR writer returns structured JSON where every sentence carries evidence ids. A reviewer agent then checks each sentence: do the cited evidence nodes exist in this case, and does every dollar amount in the sentence appear in them? In our test the writer slipped in an invented $999,999 transfer; the reviewer caught it, the writer revised, and the stored SAR came out 100% grounded. In the UI every citation is clickable and opens the exact Cypher behind it.

## Results on the synthetic benchmark

Ground truth lives outside the graph so agents can't peek. Against 71 alerts (41 false positives, five planted schemes), the offline playbook runner closed all 41 false positives with cited reasons, escalated all five schemes with zero false SAR cases, merged 22 duplicate alerts, and found five smurf accounts no rule had flagged, in about 30 seconds for the whole queue.

## What we learned about FalkorDB 6

We built on the new Rust engine (6.0.1). Traversals were fast enough to run on every agent step (most tools return in 2-25 ms on ~11k nodes and ~58k relationships), the algorithm procedures were one `CALL` away, and one instance with many isolated graphs made the multi-bank story honest rather than simulated. We hit two engine edge cases (documented with repros in the repo) and worked around both.

Hound recommends; a human decides. But the human now starts from a case that already shows its work.
