# ShopSquire — Platform Deep Dive, Delta, and SWOT

**Date:** 2026-08-12 · **HEAD:** `86a1efb3` · Measured, not estimated

---

## 1. What the numbers say

| Metric | Value |
|---|---|
| Commits (total) | **1,801** |
| Commits last 30 / 14 / 7 / 1 days | **813 / 376 / 202 / 32** |
| Python files / lines | **1,102 / 289,197** |
| Services / security / routers / ERP modules | **641 / 143 / 121 / 27** |
| Frontend TS+TSX files | 179 |
| Test files | **1,225** · 578 in `tests/services` |
| Tests in `tests/services` | **3,957 — 5 failing (99.87%)** |
| Playwright e2e specs | 40 |
| ERP/CRM/accounting connectors | **9** (SAP, Ariba, Coupa, NetSuite, Dynamics, Salesforce, HubSpot, QuickBooks, Shopify) each with an inventory variant |
| Deployment | Helm chart (deployment/service/ingress/HPA/backup CronJob) + 9 compose overlays |

~27 commits/day sustained for a month. This is not a prototype by volume; it is a mid-sized
enterprise codebase.

---

## 2. Delta progress — the honest arc

Tracked across nine assessments in six days:

| Date | State |
|---|---|
| 08-07 | Research trigger unreachable — `web` leg cost 5 against a budget of 3, had **never run**. Silent misroute to gaming laptops. |
| 08-08 | Catalogue had **zero** workstation-class SKUs. Upload→claim path absent entirely. |
| 08-09 | SearXNG CAPTCHA'd, discovery non-reproducible. Backend not launched via the demo profile. |
| 08-11 | Clarification deadlock swallowed every commercial turn. 6 personas → identical shortlist. |
| **08-12** | **Research executes on consent in 5.4s and *changes the ranking*.** Null class shipped. Per-attribute verdicts. Governed narration. **But 11/11 queries return one identical shelf.** |

**The trajectory is genuinely good.** Every defect I have raised has been either fixed or
consciously deferred — none reopened. The honesty layer in particular is now better than most
commercial products: the system routinely refuses to claim what it cannot prove.

**The single unresolved thing is large.** The product shelf is not a function of the query.
Eleven distinct queries — laptops, an ergonomic desk, ibuprofen, hobby renders, 4K production
renders — returned the byte-identical top three. A correct evidence layer is currently re-ranking
a constant.

---

## 3. Capability-by-capability

Maturity: 🟢 production-shaped · 🟡 works, needs hardening · 🟠 built, unreached · 🔴 broken

| Capability | State | Evidence |
|---|---|---|
| **Evidence & provenance ladder** | 🟢 | Tier 0–6 with per-rung `execution_status`, `billing_class`, prohibited-claim-types per publisher. Verified live. |
| **External research on consent** | 🟢 | 5.4s, 3 publishers, 8 claims compiled, **ranking moved** (`JW-818845: 4→2`). |
| **Decision Trace / audit** | 🟢 | Best artifact in the product. Bitemporal `decision_log`, `audit_chain`. |
| **Security posture** | 🟢 | 143 modules. PII NER, DLP export, SSRF defence, model-theft rate limiting, prompt-injection handling, `data_residency` citing ISO 27001 A.5.33. |
| **Multi-tenant isolation** | 🟢 | `tenant_id` threaded through 203 files. |
| **Local inference / sovereignty** | 🟢 | Ollama on-box. No customer data to any AI vendor. |
| **Governed narration** | 🟢 | Discloses authority basis; no invented benchmarks; toggleable. |
| **Deployment** | 🟡 | Helm with HPA, non-root, read-only rootfs, backup CronJob. Untested at scale. |
| **ERP/CRM connectors** | 🟡 | 9 systems, inventory variants. Fixture-backed; no production enrollment. |
| **Supplier RFQ / human gate** | 🟠 | Send-cage, quarantine, revision-bound choices, `/supplier-events`, approval endpoints — **all built, none reachable from chat**. |
| **Deadline feasibility & escalation** | 🟠 | `promise_feasibility.py`, `build_operator_escalation` — correct code, never entered. |
| **Bulk / procurement journey** | 🔴 | Every qty×deadline permutation returns the same research question. |
| **Product ranking / relevance** | 🔴 | **11/11 queries → identical top 3.** Includes pharmacy → $14,999 workstation. |
| **Domain routing** | 🔴 | Furniture asked *"which named software governs this work?"* |
| **Catalogue hygiene** | 🔴 | Duplicate SKUs, NULL categories, no MPN column. |

**The pattern is consistent and worth naming:** everything about *knowing and proving* is strong;
everything about *choosing* is weak. The platform has a superb evidence spine attached to a
retrieval layer that isn't yet doing its job.

---

## 4. What it can actually do today

**Genuinely demonstrable now:**
1. Take an ambiguous professional request and produce 1–3 competing interpretations instead of one guess.
2. Refuse to claim fit it can't prove — and say precisely which attribute is unverified.
3. Ask a human for permission before any external call, then fetch from approved publishers only.
4. Compile fetched evidence into typed requirements and **show the before/after ranking change**.
5. Produce an audit record answering "why did it recommend that, on what evidence, as at when".
6. Run entirely inside a customer's perimeter — local models, self-hosted search, no third-party AI.
7. Redact PII before anything reaches a model; block cross-border transfers by policy.

**Not demonstrable:** a correct product recommendation for an arbitrary query, any bulk/deadline
journey, or a supplier RFQ round trip from the buyer surface.

---

## 5. Who it helps, and how

### Procurement / category managers — **strongest fit today**
The buyer who must justify a 30-unit purchase to finance and audit. They don't need the "best"
laptop; they need a defensible record. ShopSquire already produces: retained purpose, competing
interpretations, which publisher established each requirement, what remains unverified, and what
the platform refused to authorise. **That artifact is the product**, and it exists.

### Suppliers — **built, blocked**
Quarantined untrusted responses, normalised offers with provenance, revision-bound choices
(split / wait / next-best / substitute / enquiry), human-only send. A supplier would receive a
*specific* RFQ citing the compiled requirement and the shortfall quantity, not "please quote
laptops". Nothing reaches them yet because the buyer can't get there.

### Warehouse / fulfilment — **partially real**
Per-location stock, transfer modelling ("7 local now, 23 transfer"), ATP, `inventory_guard`,
reorder execution, valuation. The honest deadline behaviour is genuinely good: *"inventory location
is known, but date-qualified transfer and carrier arrival evidence is missing — a fulfilment
operator must verify."* That is exactly right and most systems just promise. It is unreachable from
chat.

### E-commerce merchandisers — **weakest fit**
Ranking is the core job and ranking is the broken part. Nothing to offer here until §3's 🔴 row is
fixed.

---

## 6. SWOT

### Strengths — *why*

| Strength | Why it matters |
|---|---|
| **Evidence provenance with forbidden claim types** | Per-publisher, per-claim-type authority. Microsoft may state Hyper-V host requirements and is *barred* from authorising VM sizing. Almost nobody does this. |
| **Honest failure surfaces** | The system says "I could not obtain approved requirements" instead of guessing. In regulated buying, the refusal *is* the feature. |
| **Deterministic authority over a probabilistic model** | Model proposes, policy authorises. Survives model swaps and audit questions. |
| **Data sovereignty by construction** | Local models + self-hosted search. Removes the single biggest enterprise-AI blocker. |
| **Test discipline** | 3,957 tests at 99.87%, 40 browser journeys, no finding reopened across nine review cycles. |
| **Velocity** | 813 commits/30 days with quality holding. |

### Weaknesses — *why*

| Weakness | Why it matters |
|---|---|
| **Shelf is a constant (11/11)** | Undermines everything upstream. Perfect evidence re-ranking a fixed list is theatre. |
| **Commercial half unreachable** | Feasibility, escalation, RFQ all built and gated behind one relation-classification bug. Enormous sunk value earning nothing. |
| **Registry-bound discovery** | 31 enrolled workloads. Outside them it snaps to the nearest enrolled publisher — researching AutoCAD for a photogrammetry question and calling it "established". |
| **Two observers, no adjudication** | The gating observer sees the query; the one that sees the catalogue is rendered and ignored. |
| **Catalogue quality** | Duplicates, NULL categories, no MPN. Ranking can't beat its inputs. |
| **Surface area vs. depth** | 641 services, 121 routers for one working journey. Maintenance burden is real. |

### Opportunities — *why*

| Opportunity | Why |
|---|---|
| **Reposition as an AI-governance control plane** | The governance spine is the differentiated asset; commerce is one application. Veeam/Securiti closed a **$1.725B** acquisition for adjacent capability. |
| **Procurement audit as the wedge** | Sell the defensible record, not the recommendation. It works *today*. |
| **Regulated verticals** | Pharma, defence, government, health — where "prove why" outranks "best price" and sovereignty is mandatory. |
| **ANZ sovereignty positioning** | Local-only inference is a hard requirement for AU public sector. |
| **The failure story as marketing** | "My router mapped a cyber-range procurement to a gaming laptop and told the buyer nothing was wrong" is a stronger post than a clean demo. |

### Threats — *why*

| Threat | Why |
|---|---|
| **Ranking may be the hardest remaining problem** | Nine assessments have improved evidence; none moved ranking. It may need a different approach, not a fix. |
| **Registry curation doesn't scale** | 31 workloads by hand. Real traffic is a long tail; discovery for novel concepts is still unreached in-product. |
| **Metasearch fragility** | SearXNG is healthy today, CAPTCHA'd three days ago. Not controllable. |
| **Single-machine constraint** | 12GB VRAM shapes real architecture decisions. Not representative of deployment. |
| **Demo risk** | Any live demo can hit the identical-shelf bug in front of an audience. |
| **Solo maintenance** | 289k lines, 1,102 files, one maintainer. |

---

## 7. What I'd do next, in order

1. **Make the shelf a function of the query.** Nothing else matters until a pharmacy request stops returning a $14,999 workstation. Start by checking whether the shelf reducer reads per-hypothesis retrieval output or a fixed pool.
2. **Unblock the commercial half** — the clarification-interrupt clamp. One deterministic rule releases feasibility, escalation and RFQ, all already built and tested.
3. **Feed the post-catalog observer into the gate.** One edge; catches the confident-wrong-answer class.
4. **Catalogue hygiene** — dedupe, categories, MPN. Ranking can't exceed its inputs.
5. **Then** narrow the story. 641 services is a liability; pick the procurement-audit journey and make one path excellent end to end.

---

## 8. Verdict

ShopSquire is **further along than its demo suggests and differently shaped than its name implies.**

The commerce agent is the weakest part. The governance layer — provenance, consent, refusal,
bitemporal audit, sovereignty, per-publisher claim authority — is genuinely differentiated work that
would take a funded team months, and it is ~99.9% green across 3,957 tests.

The risk is misreading which half is the asset. Judged as a shopping assistant it looks broken,
because the part that picks products doesn't work. Judged as **an evidence-and-consent control plane
for AI acting on regulated data**, it is a strong proof-of-concept with one embarrassing bug in its
demo application.

The next month should either fix ranking properly or stop leading with it.
