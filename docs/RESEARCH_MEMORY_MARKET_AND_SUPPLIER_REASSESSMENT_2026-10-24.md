# Memory, temporal retrieval, market intelligence and supplier communications

Research reviewed 24 October 2026. This is a selected review of relevant primary sources, including September/October 2026 work. Published benchmark results were not reproduced in ShopSquire and are not evidence of its performance. Implementation recommendations below are engineering inferences, distinguished from the papers' findings.

Read alongside the [fresh execution assessment](RETEST_TDD_MVP_AND_ROADMAP_2026-10-24.md). The main product gap is completing a useful, evidence-grounded procurement task across the existing components. Adding another memory framework does not by itself resolve that gap.

## What the research changes

| Primary source and date | Relevant finding or approach | Application to ShopSquire; limits |
|---|---|---|
| [LongMemEval](https://arxiv.org/abs/2410.10813), revised March 2025 | Separates extraction, cross-session and temporal reasoning, updates and abstention; separates indexing, retrieval and reading. | Measure these abilities individually. A retained quantity is not a completed research answer. This is a conversational-memory benchmark, not a stock or email-delivery certification. |
| [LongMemEval-V2](https://arxiv.org/abs/2605.12493), May 2026, work in progress | Evaluates experience from web-agent trajectories: static/dynamic state, workflows, environment gotchas and premise awareness. Its stronger agent-based method also incurs latency costs. | Add tasks involving changed inventory, corrected requests and failed prior operations. Keep factual recall and action completion separate; do not copy its benchmark score into a commerce claim. |
| [Zep/Graphiti](https://arxiv.org/abs/2501.13956), January 2025 | Uses a temporal knowledge graph for conversational and business context while retaining historical relationships. | Keep event-validity and ingestion/knowledge time distinct. Evaluate a graph adapter only where relationship retrieval helps; canonical quantities and approvals remain database-owned. The paper is written by the system's authors, and its gains are baseline-specific. |
| [IA-RAG](https://arxiv.org/abs/2606.06044), June 2026 | Represents intervals and their temporal relationships, including uncertainty in boundaries. | Apply explicit interval checks to stock observations, quotes, calendars and deadlines. A source date or recency score alone cannot prove a quote is valid for the requested delivery window. Its temporal-QA experiments do not validate merchant operations. |
| [Threader](https://arxiv.org/abs/2609.33226), September 2026 | Proposes preserving raw interactions and retrieving coherent segments instead of repeatedly rewriting them into generated memory. | Preserve source turns with revision references alongside structured case projections. Retrieve evidence needed for the question, rather than replacing the canonical record with a model summary. Published results are not an independently reproduced system comparison here. |
| [Mem++](https://arxiv.org/abs/2610.02002), October 2026 | Preserves dated original documents and shifts selection to read time, combining lexical and semantic retrieval. | Retain original source evidence under an explicit retention policy and build rebuildable projections. Its organizational evaluation is small and synthetic; the full paper shows that simpler RAG remains stronger on some dimensions. This does not justify retaining personal data indefinitely. |
| [Industrial ReMEmbR](https://arxiv.org/abs/2610.28624), 20 October 2026 | Retrieves shared robot observations using content, position and time, with expensive descriptions generated on demand. | Useful separation of indexing from costly interpretation. Its spatial coordinates, robot encoders and fleet setting are not direct prerequisites for a shopping assistant. Do not translate its privacy design into a blanket compliance claim. |
| [Bridge](https://arxiv.org/abs/2605.19172), May 2026 | Combines regional context and historical region-time patterns for cold-start delivery-demand forecasting. | A possible later comparison for location-aware demand forecasts. Historical neighbour trajectories must be available at the forecast cutoff. This is not evidence that future purchase orders count as present stock. |
| [DeepResearch Bench](https://arxiv.org/abs/2506.11763), June 2025 | Separates report quality from retrieval and citation evaluation. | Assess whether each claim answers the question and is supported by its cited source. Counting citations or checking that a citation array is nonempty is insufficient. Build a domain-specific judged dataset rather than treating this benchmark as a procurement oracle. |
| [Chronos-2](https://arxiv.org/abs/2510.15821), October 2025 | Supports multivariate and covariate-informed zero-shot forecasting. | Consider as a shadow challenger after a reliable merchant dataset exists. Compare against the existing simple demand baselines using rolling cutoffs, calibration, cost and operational usefulness; no model adoption or performance gain was established in this review. |

## The appropriate architecture

Use structured authority for exact commercial facts, and retrieval to obtain supporting evidence:

```text
Buyer turns / uploads             Catalog / stock / calendars / supplier observations
          |                                      |
          v                                      v
Tenant + person + case + revision         Source admission + provenance + validity
          |                                      |
          v                                      v
Canonical case and event history <---- Versioned evidence references
          |                                      |
          |                            Lexical + semantic retrieval
          |                            Optional graph expansion
          |                                      |
          |                            Recheck scope/time/permissions
          |                                      |
          +----------> Task-specific evidence <----+
                            |
                   +--------+---------+
                   |                  |
             Cited market answer   Supplier draft artifact
                   |                  |
             Advisory only       Recipient + body review
                                      |
                            Separate exact-effect approval
                                      |
                            Outbox + bounded transport
                                      |
                            Reconcile uncertain delivery
```

This is a target arrangement using existing seams, not a claim that the complete chain is certified. The case read/draft path, market consumer, approval journey and outbox already exist. Their integration, useful research positives and operational qualification remain separate gates.

For ShopSquire, spatial context first means distinct fields for buyer destination, stock location, source geography and workload/site context. A university mentioned in a requirement is not automatically a delivery address. A destination correction must not replace the workload. A global commodity observation must not silently become a local laptop lead-time estimate.

Temporal context should distinguish:

- When the event happened, when the system learned it, and its effective interval.
- The case revision, quote expiry, stock-hold expiry and source cutoff used for an answer.
- The user's delivery expression and the timezone/calendar used to resolve it.
- A historical answer as known then, versus a current answer using later corrections.

Never replace these checks with embedding similarity, a graph edge or a model's confidence. A correction can supersede the current projection while retaining the earlier event under the applicable retention policy. Erasure must reach raw records, caches, derived indexes and exports within the defined scope.

## What the fresh checks show about memory

The browser can retain the amended 40-unit request, AUD 1,500 per-unit budget and Sydney destination across task changes and reload. The separate owned Redis checks exercise cross-instance/process erasure and partition/restart behaviour. These are useful positives, not universal privacy proof.

A new fault-injection probe exposes an additional semantic-cache boundary: `set_versioned` writes the value before registering its erasure index and suppresses registration failure. A replacement instance can then erase zero indexed entries and still retrieve the value. The conversation-memory implementation has a different atomic-write mechanism; its passing tests cannot certify this separate cache path. Reproduce and repair this boundary before expanding persistent memory.

The live-enabled research workflow did not fetch an approved source: its research outcome recorded `publisher_not_yet_accepted`, zero accepted claims and `fetch_status=not_attempted`; the response also reported an unavailable workload interpreter. The retained facts still survived. This directly demonstrates why memory recall and research completion need separate evaluations.

The current HippoGraph recall implementation is a bounded spreading-activation approximation, not an implementation of every algorithm named above. It can support evidence discovery and explanations. Qualification and commercial authority must continue to depend on admitted evidence and explicit state transitions.

## Market intelligence should answer a defined question

Distinguish four input families: authoritative merchant stock; attributable supplier quotes; internal demand observations; and external market context. They have different rights, freshness, units and geographical scope. Forecasts are another derived category, with uncertainty and backtesting requirements.

The fresh live USGS protocol test passed against the official ScienceBase source. That is useful evidence for that source adapter. It does not supply laptop stock or supplier lead times, and it does not complete the ordinary-chat producer-to-citation workflow.

The new assessment probes identify two immediate issues:

1. Explicit malformed `effective_from` dates are silently replaced with the observation time by the consumer's fallback. Missing optional dates and invalid supplied dates need different dispositions.
2. A lead-time question receives `delivery_status=available` when the only admitted finding describes demand. It is SKU-relevant but does not answer the requested measurement. A partial answer must identify what is and is not supported.

A useful answer should state the requested measurement and region, relevant observation or estimate, time window, source, uncertainty and its effect on the current request. Missing supply evidence should produce a clear limitation and a next useful question, without inventing a lead time.

Required tests include current relevant positives and expired, malformed, unrelated, contradictory, withdrawn, duplicate and unavailable-source negatives. Test support for individual claims, not just citation presence. Measure relevance and freshness separately from forecast accuracy.

## Better supplier email communications

The exact fictional 40/15/25 workflow already drafts 25 units correctly. Without accepted inventory coverage, the live-enabled conversation correctly produces a provisional 40-unit availability enquiry with unknown shortfall. Preserve that distinction.

The chat preview and approved supplier journey currently compose different bodies: the preview includes destination/budget details, while the journey's reviewed message is a short SKU/shortfall enquiry. The approval panel displays its own message, so this review is not claiming an unreviewed body substitution. The product improvement is a shared versioned draft artifact that carries the relevant agreed fields through review and approval.

That artifact should contain the current case/revision, product/specification, original demand, verified coverage, exact shortfall or explicit unknown, delivery location/window, currency and quantity units, and requested quotation fields. Ask for availability, unit pricing, freight, minimum order quantity, lead time and quote expiry. Make inclusion of the buyer's budget a visible review choice.

Keep internal reasoning and market citations in the application unless useful and appropriate for the recipient. Generate wording from validated fields; an optional language-model polish must preserve protected numbers, identifiers and commitments. Avoid authorising a purchase through an enquiry.

Recipient resolution, editing, approval and dispatch are different steps. Changes to recipient, quantity, price scope, destination, body or case revision must invalidate the old approval where they change its effect. Preserve idempotency, reply identity checks and explicit uncertainty after a transport timeout. A provider acknowledgement is not proof that a person read or accepted the enquiry.

Before calling this MVP-ready, prove a useful ordinary buyer request can reach a grounded offer, a current-stock calculation and the exact reviewed draft; then prove the same journey survives amendments and unavailable evidence. Add complex spatial models or another memory framework only after a held-out comparison shows a concrete benefit.
