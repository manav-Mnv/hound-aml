# Demo video script (target 3:00)

Record at 1440x900 or larger. Before recording: press **Reset** (top right) so the queue is fresh.

**0:00 - Hook (talking head or title card, 15s)**
"Banks review millions of alerts a year and 90-95% of them are false positives. Analysts stitch accounts, devices and old cases together by hand. Hound puts all of that in one FalkorDB graph and lets agents follow the money."

**0:15 - The queue (20s)** Investigate tab. "71 alerts from six ordinary threshold rules, written in Cypher. The triage agent scored all of them in a fraction of a second from graph features: shared devices, new accounts, consortium hits, prior cases. And it grouped them: these eight alerts are one identity cluster."

**0:35 - Mule ring (50s)** Click the top alert (Whitney Walker), *Investigate with Hound*. While it runs: "The investigator reads its playbook and lessons from the graph. Every tool is a Cypher query; watch the subgraph grow." Point at: WCC identity cluster (two phones, one IP, eight new accounts) → pass-through 95% in hours → trace to Ronan Pike → CoinHarbor in XQ → **consortium hit: Beta Credit Union reported this phone in September**. "Two banks, two isolated graphs in the same FalkorDB; only hashed identifiers are shared." Show it consolidating the 7 other alerts.

**1:25 - Traceable SAR (30s)** SAR tab. "Every sentence cites evidence. Click one" → evidence tab shows the exact Cypher. "A reviewer agent checks every amount against the evidence it cites; anything invented gets sent back." Approve & file SAR → toast: identifiers shared with the consortium.

**1:55 - False positive with memory (30s)** Pick *Brightline Payroll Services* (fan-out). Investigate. "Rules see 160 payees and panic. Hound recalls an analyst's lesson from August, attached to this exact company in the graph, checks the batches are pre-funded, and closes it with a cited rationale." Add an analyst note → "saved as a lesson for next time".

**2:25 - Sanctions (15s)** Bluefin Marine Imports (high-risk wire). "The rule fired for geography; the graph finds the real problem: the supplier is 55% owned by blocked persons through a holding company. Blocked under OFAC's 50% rule though it isn't listed."

**2:40 - Proof (20s)** Benchmark tab: 41/41 false positives closed with reasons, 5/5 schemes, 0 false SARs, 5 accounts no rule flagged. Memory tab: cases, lessons, playbooks, agent runs as a graph. "It also runs as an MCP server, so Claude Desktop can use the same tools."

**3:00 - Close** "Hound: follows the money, remembers every case, shows its work. Built on FalkorDB 6."
