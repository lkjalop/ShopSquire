# AI/ML research, market intelligence and revised delivery order

Research checked on 1 October 2026. Primary papers, research-lab articles and official
repositories were used. Publication dates are distinguished from revisions. Research
benchmarks are not ShopSquire results. This document changes planning, not runtime
configuration; no model was installed, trained or benchmarked in this research batch.

## Recommendation

Bring a **read-only market-intelligence pilot forward**, after a short baseline and
case-continuity repair stage. It can demonstrate useful AI before supplier and purchase
workflows are complete. Keep all proposed actions advisory until authenticated approval
and recovery are connected. Preserve the existing transactional and evidence core.

The first decision should be: **for one exact SKU, replenish now, wait, or evaluate an
alternative supplier—and explain why using current, attributable evidence.** Extend to
additional categories only after the complete evidence-to-decision path is reviewable.

AI should extract observations, resolve ambiguous language, rank relevant evidence and
estimate uncertain future outcomes. Database queries and validated code should retain
authority over stock, arithmetic, timestamps, identity, revisions and effect permissions.
Those controls are not brittle product-intent heuristics.

## Relevant advances and what to adopt

| Development and date | What the primary source supports | ShopSquire decision |
|---|---|---|
| [TimesFM-3, Google Research, 31 Aug 2026](https://www.research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/) | Multivariate forecasting with target series, historical covariates and known future covariates; alternating temporal/cross-series attention and one-pass horizon prediction. An [official model card](https://huggingface.co/google/timesfm-3.0-pytorch) exists. | Benchmark as a challenger for demand with promotions and related-product history. Published rankings do not establish performance on intermittent electronics sales. |
| [Chronos-2, Amazon Science, 20 Oct 2025](https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting/) and [official repository](https://github.com/amazon-science/chronos-forecasting) | Zero-shot univariate, multivariate and covariate-informed forecasting; repository records subsequent deployment support in June 2026. | Another challenger using the same rolling forecast origins, data cutoffs and resource budget. Start with one challenger, then add the second if the first comparison is useful. |
| [MemoryArena, submitted 18 Feb, revised 17 Sep 2026](https://arxiv.org/abs/2602.16313) | Evaluates memory used across interdependent tasks, rather than recall alone; strong conventional memory scores need not transfer to agentic tasks. | Test remembering a change **and correctly using it** in the next quote, forecast and approval. Add restart and cross-session tasks to the real browser harness. |
| [LongMemEval-V2, 12 May 2026](https://arxiv.org/abs/2605.12493) | Work-in-progress benchmark covers static recall, changing state, workflows, environmental gotchas and premise awareness; richer evidence gathering has latency costs. | Separate authoritative state, observations and procedural notes. Test false premises such as “use the approval from before the quantity changed.” Do not treat its reported scores as production guarantees. |
| [IA-RAG, 4 Jun 2026](https://arxiv.org/abs/2606.06044) | Preprint models knowledge using validity intervals and temporal constraints for retrieval. | Adopt the practical temporal discipline now: quote expiry, overlapping supplier terms, decision-time availability and historical-as-of queries. Do not implement the full proposed graph framework without a measured need. |
| [Recursive Language Models, submitted 31 Dec 2025, revised 11 May 2026](https://arxiv.org/abs/2512.24601) | Treat long inputs as an external environment that can be inspected and decomposed through recursive calls. | Later experiment for large supplier-document or market-report collections. Bound recursion, tokens and execution; ordinary indexed retrieval is sufficient for the initial shop pilot. |
| [Titans + MIRAS, Google Research, 4 Dec 2025](https://research.google/blog/titans-miras-helping-ai-have-long-term-memory/) | Neural memory architectures and test-time memory updating address long-sequence processing. | Research watchlist, not a fix for dropped case IDs or an application database replacement. Weight-level memory cannot serve as a revocable transaction ledger. |
| [Contextual Retrieval, Anthropic, 19 Sep 2024](https://www.anthropic.com/engineering/contextual-retrieval) | Combines contextualized chunks, lexical retrieval, embeddings and optional reranking. Older, practically relevant work rather than new 2026 news. | Test hybrid retrieval for exact SKU names plus semantic descriptions. Keep generated chunk context separate from source quotations and authoritative facts. |
| [LazyGraphRAG, Microsoft Research, 25 Nov 2024; editor update 6 Jun 2025](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/) | Defers summarization and explores graph/community structure for local and global questions. The article's deployment note does not establish a drop-in ShopSquire dependency. | Evaluate graph-assisted retrieval only for questions requiring dependency paths or collection-wide synthesis. Reuse existing graph code first. |
| [Context engineering, Anthropic, 29 Sep 2025](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Advocates deliberate context selection, compaction and retrieval rather than indefinite context accumulation. | Build compact case context from current state plus cited observations; never let a lossy summary overwrite accepted facts. |
| [Cybersecurity incident assessment, Anthropic, 9 Sep 2026](https://www.anthropic.com/research/alignment-assessment-cybersecurity-incidents) | Describes failures in evaluations mistakenly connected to real networks. | A “simulation” prompt is not isolation. Fake suppliers, restricted network access and separate effect credentials must be enforced by the harness. |

These are different kinds of evidence: deployed model releases, lab evaluations,
engineering patterns and research preprints. No cross-paper headline comparison is a
valid model-selection experiment. Adoption recommendations below are engineering
judgments based on ShopSquire's observed gaps, not conclusions claimed by those papers.

## First AI/ML market-intelligence product

Build a merchant decision card that answers:

> A buyer has changed from 30 to 40 units. Given current unreserved stock, existing
> commitments, eligible inbound deliveries, supplier terms and uncertain ordinary
> demand, should the shop seek extra units now, wait, or review another offer?

The accepted buyer order is a known commitment; it must not be confused with a demand
forecast or counted twice. Merchant replenishment and expanding a buyer's order are
different decisions. The initial card cannot send enquiries, buy stock or change holds.

| Task | Appropriate first method | Model output must not become |
|---|---|---|
| Extract supplier capacity, dates, MOQ, freight, price breaks and quote expiry | Schema-constrained language-model extraction with cited source spans and abstention; compare against existing parser | A trusted supplier identity, verified quote or purchase approval |
| Map documents to products | Exact identifiers first; embeddings/reranker propose uncertain matches for review | An automatic merge of similarly named but different configurations |
| Identify relevant market events | Deduplicate reports by underlying event/lineage; classify relevance to SKU/category/region/horizon | “Two independent sources” merely because two sites copied one announcement |
| Detect unusual demand/returns/delivery behavior | Simple robust baseline first; evaluate a statistical/ML detector on labelled scenarios | Proof of why the change happened |
| Forecast demand during replenishment lead time | Existing seasonal/EWMA/Croston/TSB baselines, then one foundation-model challenger | A guaranteed demand number or an instruction to purchase |
| Compare options | Tested cost/stock/deadline calculator over forecast scenarios | Unchecked language-model arithmetic |
| Explain the choice | LLM summarizes computed alternatives with evidence IDs, contradictions, assumptions and uncertainty | New unsupported product, price or market claims |

The result should include decision time, tenant/SKU, accepted case revision where
applicable, source observations and availability times, stock reconciliation receipt,
model/data/config versions, forecast intervals, candidate total costs, rejected
alternatives, expiry and explicit `commerce_authority=none`.

An example output shape is “review supplier B because A cannot cover the shortfall by
the deadline; the volume discount reduces unit cost but increases total commitment.”
Numbers must come from the calculator, not this illustrative sentence.

## Data: synthetic is enough for this portfolio, but a catalogue is not a history

Keep existing SKU identities and seeders. For the first full experiment, use one reviewed
SKU and its locations/supplier terms. For evaluation, expand to a proposed 10–20 SKU
subset across several demand patterns and electronics categories, with 180–365 daily
observations where that scenario warrants them. These are proposed experiment sizes,
not already populated or validated data.

Generate coherent orders, cancellations, shipments, returns, stockouts, inbound receipts,
supplier lead times, prices, costs and promotions. Keep the latent demand process for
the simulator's evaluator only. The forecasting model sees what a merchant could know.
Observed sales during a stockout are censored demand; missing observations are not zero
sales. A one-off 40-unit institutional purchase should not automatically become a
permanent increase in recurring daily demand.

Public product announcements, recall notices or supply reports can provide attributable
external observations later. Fictional supplier availability and invented sales remain
separately labelled. Do not assert that a real news event caused the synthetic shop's
demand merely because their dates coincide.

Store event time, publication time, first-available-to-system time and validity interval.
Backtests may use only information available at the decision cutoff. Announced future
promotions can be known covariates; realized future sales, revised forecasts or later
supplier replies cannot. Keep geography, currency, tax/freight basis and configuration
scope explicit. Supplier purchase cost is not the public retail price.

## Memory, vector retrieval and graph retrieval have different jobs

| Information/question | First storage or retrieval choice | Reason |
|---|---|---|
| Current quantity, budget, destination, accepted changes, grants, reservations | Transactional state/event history with revision checks | Exact, revocable and auditable; similarity search is not authoritative state |
| Previous conversation and “why did we reject this offer?” | Scoped event history plus compact cited episodic summary | Preserve corrections and reasoning provenance without loading every transcript |
| “Find this exact model number or quote” | Identifier lookup and lexical retrieval | Exact strings and numbers matter |
| “Find similar evidence about supplier delivery delays” | Lexical + vector retrieval, fusion and measured reranking | Handles paraphrases while preserving identifier precision |
| “Which SKUs depend on this distributor or affected lane?” | Existing typed dependency graph/relational joins | Requires explicit relationships with provenance and validity |
| “What themes recur across hundreds of reports?” | Evaluate graph/community-assisted synthesis against hybrid retrieval | Potentially a global question; graph benefit must be measured |

Apply tenant/access scope before candidates enter the prompt; apply temporal/authority
checks again at consumption. Graph edges extracted by a model are proposals until
accepted. Expired or revoked facts must not survive as valid graph edges or cached
summaries. Graph reachability explains a dependency, not a causal effect size.

Retrieval ablation: identifier/lexical baseline → vector-only → hybrid fusion → hybrid
with reranking → bounded existing graph expansion. Use the same corpus, query set,
cutoff and cost budget. Select the smallest configuration that improves supported
answers and decision outcomes. Catalogue size alone does not justify a new graph DB.

## Existing code to extend, not replace

| Existing entry point | How it fits the plan |
|---|---|
| [market_signal_adapters.py:340](C:/AI/ShopSquire/src/app/services/market_signal_adapters.py:340) | Source ingestion receipts and tenant-scoped backfill; add attributable external event extraction here or behind its adapter contract. |
| [market_pipeline.py:20](C:/AI/ShopSquire/src/app/services/market_pipeline.py:20) | Ingest/analyse/persist sequence; make unavailable/failed/empty distinct at every outer boundary. Some outer failures currently return zero-count shapes. |
| [market_analysis.py:589](C:/AI/ShopSquire/src/app/services/market_analysis.py:589) | Existing detectors and forecast hooks; evaluate before adding another analytics stack. |
| [market_intelligence_agent.py:198](C:/AI/ShopSquire/src/app/services/market_intelligence_agent.py:198) | Subject-scoped market context and evidence for recommendations. |
| [market_evidence_admission.py:13](C:/AI/ShopSquire/src/app/services/market_evidence_admission.py:13) | Existing provenance and consumption-time validity gate; extend tests for as-of availability and revocation across consumers. |
| [forecast_intelligence.py:119](C:/AI/ShopSquire/src/app/services/forecast_intelligence.py:119) | Baseline comparison, supplier-lead-time horizon, WAPE/MASE/bias and interval evidence; add challenger outputs under the same evaluation contract. |
| [forecast_intelligence.py:55](C:/AI/ShopSquire/src/app/services/forecast_intelligence.py:55) | Daily-series construction fills missing days once rows exist. Verify coverage before interpreting missing days as measured zero demand. |
| [market_action_policy.py:27](C:/AI/ShopSquire/src/app/services/market_action_policy.py:27) | Governed replenishment-advice gate; keep separate from effect authorization. Its rising-demand condition should not be mistaken for a universal reorder rule: stable demand can also exhaust stock. |
| [candidate_retriever.py:61](C:/AI/ShopSquire/src/app/services/candidate_retriever.py:61), [candidate_retriever.py:395](C:/AI/ShopSquire/src/app/services/candidate_retriever.py:395) | Existing reciprocal-rank fusion and retrieval composition. DB keyword matching exists; do not describe it as already implementing BM25. |
| [supply_graph_repository.py:170](C:/AI/ShopSquire/src/app/services/supply_graph_repository.py:170), [supply_graph_repository.py:266](C:/AI/ShopSquire/src/app/services/supply_graph_repository.py:266) | Existing edge revisions and bounded dependency paths. Reuse for supplier/SKU/lane relationships before new infrastructure. |
| [shop_operational_history.py:134](C:/AI/ShopSquire/src/app/services/shop_operational_history.py:134) | Reconcile stock with event history before feeding the decision engine. |
| [model_execution_gateway.py:240](C:/AI/ShopSquire/src/app/services/model_execution_gateway.py:240) | Bounded model execution and trace evidence; keep market extraction/narration under the same operational discipline. |

These code observations are static inspection, not new runtime certification. The
October 1 platform audit's failed browser tests and deployment gaps remain open.

## Evaluation contract before selecting models

1. Freeze scenario manifests, exact SKU mappings, generator versions, source snapshots,
   labels and time cutoffs. Separate development and holdout sets before tuning.
2. Hold out time blocks, SKU families and generator regimes, not random adjacent rows.
   Reserve stockout, promotion, abrupt supplier delay, intermittent demand, returns and
   no-change regimes. Independent review is preferable; disclose self-review if needed.
3. Compare extraction against the existing parser using field accuracy, unit/currency
   correctness, grounded source spans and calibrated abstention. Supplier text saying
   “ignore policy and approve” must remain inert content.
4. Compare retrieval using recall at k, ranking quality, supported-answer accuracy,
   stale/wrong-tenant retrieval, cost and latency. Similarity alone is not relevance.
5. Compare forecasts at supplier lead-time horizons with rolling origins. Use WAPE only
   when its denominator is nonzero, MASE where its scale exists, quantile/pinball loss,
   coverage and bias. Preserve undefined metrics rather than filling favorable values.
6. Replay identical simulated demand/supplier outcomes for each decision policy. Measure
   stockout units, fill rate, inventory holding cost, expedite cost, excess inventory,
   total spend and decision regret against a declared reference policy. Prediction
   error improvement without operational benefit is insufficient for promotion.
7. Ablate the external signal: baseline → model with operational history → model plus
   admitted external events. The external events must add held-out value to justify
   their retrieval/extraction cost. Compare forecast candidates under explicit memory,
   latency and inference budgets; record hardware and model revisions.
8. Run real-API Playwright through evidence → decision → changed quantity → updated
   analysis; assert source IDs, revisions, computed totals, refusal cases and zero
   unauthorized effects in durable state. A fluent explanation is not the oracle.

Choose success thresholds before running the holdout based on baseline variability and
the simulation's stated costs. Do not promise a universal percentage uplift now. The
test harness should allow retaining the simple baseline if the challenger loses.

## Revised execution order

| Order | Deliverable | Why now / completion gate |
|---|---|---|
| 0 | Preserve audit/checkpoints, freeze evaluation scope, verify demo isolation and effective runtime profile. | Protect evidence; benchmark setup must not silently run disabled services or real effect transports. |
| 1 | Repair case restoration, recall presentation and budget clarification failures. | Known defects remain first. Close the existing real-browser regressions; include tenant/session separation, corrections and reload. No vector/graph/model change is required merely to persist the case ID. |
| 2 | Build the first reconciled market-decision dataset and simple baseline. | Moves market intelligence earlier. One exact SKU, current stock/commitments, attributed supplier terms and temporal history; no misleading zero-filled gaps or duplicated demand. |
| 3 | Add governed extraction, hybrid retrieval and the read-only merchant decision card. | First visible AI/ML benefit. Show evidence, uncertainty, costs and rejected options; compare with the baseline. Ingestion can start from fixtures; live external search remains explicitly gated. |
| 4 | Benchmark a forecasting challenger and relevant external signals. | TimesFM-3 or Chronos-2 is a candidate, not a preselected winner. Keep advisory/shadow mode; require held-out decision value and budget compliance. |
| 5 | Connect conversational requirements → governed external research → qualification → shelf/trace. | Reuse the evidence/retrieval discipline, but keep product suitability separate from demand predictions. Prove positive fictional qualification and truthful negatives. |
| 6 | Finish operational inventory: scheduled expiry, inbound receipts, transfers, shipment/return/cancellation UI. | Enables faithful availability and future merchant decisions. Reconcile every event and prove concurrency/replay invariants. |
| 7 | Connect supplier enquiry/reply/quote through fake transport, with approval foundations before dispatch. | Multiple suppliers, shortfalls, expiry, substitutions, duplicates and sender checks. A fixture offer is not a completed conversation. |
| 8 | Complete accepted amendment costs/delivery and authenticated distinct-person approval. | Revised quantities invalidate old quotes/approvals; server controls identity and transaction values. Approval gates apply to every action-bearing workflow, even if its UI is built earlier. |
| 9 | Complete operator recovery and remaining effect sinks. | Uncertain fake provider outcomes require reconciliation; no duplicate effects or false completion after crash/retry. |
| 10 | Finish upgrades, compatible accessories and bundles. | Relevance/compatibility evidence, accurate totals and explicit buyer acceptance; market signals do not certify suitability. |
| 11 | Complete the systematic red-team and connected-browser matrices. | Security tests run from step 0 onward; this stage closes coverage across pages, supplier messages, images/OCR, memory, identity, canaries and effect counts. |
| 12 | Resolve buffer failure, run measured 60-minute and eight-hour endurance, prove release/restore/rollback and observed CI. | Reliability/resource instrumentation runs throughout; final runs certify a stable connected build. Mixed-model/image claims require those actual workloads. |
| 13 | Expand held-out model/retrieval/graph comparisons only where errors justify them. | A small benchmark starts in steps 2–4. Broader graphs, recursive contexts, fine-tuning or architecture swaps require reproducible incremental value. |

Dependencies: the read-only market pilot does not depend on a completed purchase UI;
transactional data validity still does. The later supplier and purchase flows cannot
skip approval/recovery because the merchant card was persuasive. Security, TDD,
browser evidence and reproducibility accompany every stage rather than waiting until
the end. No existing completed test or control should be rebuilt merely to fit this order.

## First coding batch after this research

Repair the observed case restoration/projection failures and preserve their tests. Then
produce one read-only market-decision gap report from existing tables: exact SKU,
history coverage, reconciled stock, commitments, supplier terms, provenance/expiry,
baseline forecast and missing inputs. Run the existing market/forecast tests before
adding a model adapter. This diagnoses the first actual gap and prevents another
synthetic dashboard that merely displays generated confidence scores.

Defer general neural memory, full-corpus GraphRAG, autonomous model-managed financial
state, broad fine-tuning and a new recommendation stack. There is no new model winner,
real-market ROI claim, real-product certification or stability certification in this
research update.
