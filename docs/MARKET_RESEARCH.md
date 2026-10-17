# Market research (fact-checked, October 2026)

Each claim below was checked against the primary source where one exists; secondary-only claims are marked.

## The cost of the status quo

| Claim | Figure | Source | Check |
|---|---|---|---|
| Share of TM alerts that are false positives | ~90-95% | NICE Actimize survey ([report](https://www.niceactimize.com/Documents/aml_ai_in_aml_insights_report.pdf)); widely repeated by vendors citing PwC/McKinsey | Vendor survey; definition = alert not resulting in a SAR. Treat as industry consensus, not a peer-reviewed number. |
| SARs filed with FinCEN | 4.7M in FY2024 (4.6M FY2023, 4.3M FY2022) | FinCEN public infographic (FY2024) | Calendar-year originals ~3.8M (Thomson Reuters); difference is amended/continuing SARs. |
| Global financial-crime compliance cost | US$206.1B (2023 study) | [LexisNexis Risk Solutions press release, Sept 2023](https://risk.lexisnexis.com/global/en/about-us/press-room/press-release/20230926-global-financial-crime-compliance-costs) | Latest edition found; newer editions may exist. |
| Money laundered globally | ~2-5% of global GDP | IMF 1998 consensus range; UNODC 2011 estimated 2.7% of GDP (~$1.6T, 2009) | The often-quoted "$800B-$2T, UNODC" is a restatement of the old IMF range. |
| Largest BSA penalty | TD Bank ~$3.09B, guilty plea, Oct 10 2024 | DOJ announcement (via [NBC](https://www.nbcnews.com/business/business-news/td-bank-pleads-guilty-money-laundering-case-will-pay-3-billion-penalti-rcna174912), [Jurist](https://www.jurist.org/news/2024/10/td-bank-pleads-guilty-to-violating-anti-money-laundering-law/)) | Multiple outlets agree: $670M+ laundered by three networks; ~92% of transactions unmonitored 2018-2024. |
| Money mules (UK) | 238,396 suspected mule accounts offboarded in 2025 | [FCA multi-firm review](https://www.fca.org.uk/publications/multi-firm-reviews/money-mules-activity-cashing-out-findings) | 2025 category changed, not directly comparable with 2023-24. |
| Money mules (India) | ~24.67 lakh suspected mule accounts in I4C's Suspect Registry; ~4.5 lakh frozen in one 2024 drive | Indian news reporting (Business Standard and others) | Secondary sources; figures not fully reconciled. |

## The market is moving to agentic investigation

- **FIS + Anthropic, Financial Crimes AI Agent** (press release, May 4 2026): assembles evidence across core systems, evaluates typologies, aims to compress investigations from days to minutes; Anthropic stressed that "every conclusion the agent reaches links back to its source data". GA planned 2H 2026. ([FIS](https://www.fisglobal.com/about-us/media-room/press-release/2026/fis-brings-agentic-ai-to-banking-with-anthropic-starting-with-financial-crimes)) — verified from primary source.
- **Nasdaq Verafin, Agentic AML Analyst** (June 10 2026): automates triage of AML alerts, starting with cash structuring. ([Verafin](https://verafin.com/news/nasdaq-verafin-announces-expansion-of-its-agentic-ai-workforce/)) — verified from primary source.

Neither announcement describes a graph context layer. Hound's position: the same agentic workflow, but with relationships, memory and evidence stored in one graph, which is what makes cross-alert de-duplication, ring discovery and traceable SARs cheap.

## Regulatory hooks Hound implements

| Rule | What it says | Hound |
|---|---|---|
| CTR / structuring | Cash over $10,000 requires a CTR (31 CFR 1010.311); breaking it up to evade reporting is structuring (31 U.S.C. 5324; 31 CFR 1010.100(xx)) — no single deposit needs to exceed $10k | `cash_structuring_profile`: band analysis vs CTR-filed deposits, linked depositors (smurfs) |
| OFAC 50 Percent Rule (2014 guidance) | Entities owned 50%+ in aggregate, directly or indirectly, by blocked persons are blocked even if unlisted | `sanctions_exposure`: ownership chains + fixed-point aggregation through blocked entities |
| SAR narrative | FinCEN guidance: cover who, what, when, where, why (and how); narrative must stand alone | SAR writer schema + grounding reviewer |
| 314(b) information sharing | FinCEN fact sheet, **June 12 2026**: real-time sharing permitted; fraud and money-mule schemes in scope; associations of financial institutions may share | `hound:consortium` graph with keyed hashes; published on SAR approval |

## Competitive scan (this hackathon)

A GitHub search on Oct 16 found ~60 public FalkorDB hackathon repos; at least two fraud projects ("FraudGraph": chat + 7 tools + MCP; "FraudTrace AI": deterministic exploration). Neither models AML compliance workflow (alert queue → case → SAR), memory across cases, cross-bank sharing, sanctions ownership, or measured false-positive reduction.
