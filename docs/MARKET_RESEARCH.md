# Market research (fact-checked, October 2026)

Every claim links to a source that was opened and checked on 2026-10-17. Primary sources (regulator, issuer, law) are used wherever they exist; secondary-only claims are marked. Some publishers (Verafin, FIS) block automated link checkers but open normally in a browser.

## The cost of the status quo

| Claim | Figure | Source | Notes |
|---|---|---|---|
| Share of transaction-monitoring alerts that are false positives | "almost 95 percent", some institutions higher | NICE Actimize, *AI in AML* insights report ([archived PDF](https://web.archive.org/web/20240508024800/https://www.niceactimize.com/Documents/aml_ai_in_aml_insights_report.pdf); original link now offline) | Vendor survey; defines a false positive as an alert that does not lead to a SAR. The figure is repeated widely in industry blogs (e.g. [Flagright](https://www.flagright.com/post/understanding-false-positives-in-transaction-monitoring)) but this survey is the only one found with a stated method. |
| SARs filed | 4.7 million in FY2024, about 12,870 a day | [ABA Banking Journal, reporting FinCEN's FY2024 figures](https://bankingjournal.aba.com/2025/06/fincen-releases-figures-on-bsa-filings/) | Secondary report of FinCEN data. Calendar-year originals were about 3.8M ([Thomson Reuters](https://www.thomsonreuters.com/en/institute/articles/sars-report-2024)); the gap is amended and continuing-activity SARs. |
| Global financial-crime compliance cost | US$206.1 billion (2023 study) | [LexisNexis Risk Solutions press release, 26 Sept 2023](https://risk.lexisnexis.com/global/en/about-us/press-room/press-release/20230926-global-financial-crime-compliance-costs) | Latest edition found. |
| Money laundered globally | about 2.7% of global GDP (~US$1.6 trillion in 2009) | [UNODC, *Estimating illicit financial flows* (2011, PDF)](https://www.unodc.org/documents/data-and-analysis/Studies/Illicit_financial_flows_2011_web.pdf); [UNODC money-laundering overview](https://www.unodc.org/unodc/en/money-laundering/overview.html) | UNODC says this is consistent with the IMF's older 2-5% "consensus range". The often-quoted "$800B-$2T" is that IMF range restated, not a new estimate. |
| Largest Bank Secrecy Act penalty | TD Bank, about US$3 billion, guilty plea on 10 Oct 2024; three networks moved $670M+ | [NBC News](https://www.nbcnews.com/business/business-news/td-bank-pleads-guilty-money-laundering-case-will-pay-3-billion-penalti-rcna174912), [CBC](https://www.cbc.ca/news/business/td-bank-penalties-1.7348819) | Secondary reports of the DOJ announcement; outlets agree on the figures. |
| Money mules, UK | 238,396 suspected mule accounts offboarded in 2025 (184,935 in 2023) | [FCA multi-firm review](https://www.fca.org.uk/publications/multi-firm-reviews/money-mules-activity-cashing-out-findings) | 2025 reporting category changed, so not directly comparable with earlier years. |
| Money mules, India | about 4.5 lakh mule accounts frozen in one year | [Business Standard, Nov 2024](https://www.business-standard.com/india-news/centre-freezes-450-000-mule-bank-accounts-used-in-cyber-fraud-schemes-124111200320_1.html) | News report of government figures. |

## The market is moving to agentic investigation

- **FIS + Anthropic, Financial Crimes AI Agent** (4 May 2026): assembles evidence across core systems, evaluates typologies, aims to compress AML investigations from days to minutes; general availability planned for 2H 2026. [FIS press release](https://www.fisglobal.com/about-us/media-room/press-release/2026/fis-brings-agentic-ai-to-banking-with-anthropic-starting-with-financial-crimes)
- **Nasdaq Verafin, Agentic AML Analyst** (10 June 2026): automates AML alert triage, starting with cash-structuring alerts. [Verafin announcement](https://verafin.com/news/nasdaq-verafin-announces-expansion-of-its-agentic-ai-workforce/)

Neither announcement describes a graph context layer. Hound's position: the same agentic workflow, with relationships, memory and evidence stored in one graph, which makes cross-alert de-duplication, ring discovery and traceable SARs cheap.

## Regulatory hooks Hound implements

| Rule | What it says | Source | Hound |
|---|---|---|---|
| Currency Transaction Reports | Cash transactions over $10,000 must be reported | [31 CFR 1010.311 (eCFR)](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1010/subpart-C/section-1010.311) | Rule R1, `cash_structuring_profile` (CTR-filed vs $8k-$10k band) |
| Structuring | Breaking up transactions to evade reporting is a crime | [31 U.S.C. 5324 (Cornell LII)](https://www.law.cornell.edu/uscode/text/31/5324) | Linked-depositor (smurf) detection |
| OFAC 50 Percent Rule (2014 guidance) | Entities owned 50% or more in aggregate, directly or indirectly, by blocked persons are blocked even if unlisted | [OFAC FAQs, topic 1521](https://ofac.treasury.gov/faqs/topic/1521) | `sanctions_exposure`: ownership chains + fixed-point aggregation through blocked entities |
| SAR narrative | Narratives should cover who, what, when, where and why | [FinCEN guidance on common SAR errors](https://www.fincen.gov/resources/statutes-regulations/guidance/suggestions-addressing-common-errors-noted-suspicious) | SAR writer schema + grounding reviewer |
| 314(b) information sharing | FinCEN fact sheet, 12 June 2026: real-time sharing permitted; fraud and money-mule schemes in scope; associations of financial institutions may share | [FinCEN 314(b) fact sheet (PDF)](https://www.fincen.gov/system/files/shared/314bfactsheet.pdf) | `hound:consortium` graph of keyed hashes, published on SAR approval |

## Competitive scan (this hackathon)

A GitHub search on 16 Oct 2026 found about 60 public FalkorDB hackathon repositories, including at least two fraud projects (one chat-plus-tools with MCP, one deterministic graph explorer). Neither models the AML compliance workflow (alert queue → case → SAR), memory across cases, cross-bank sharing, sanctions ownership, or measured false-positive reduction.
