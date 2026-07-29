# ShopSquire AI/ML Portfolio and Interview Demo Guide

## The one-sentence position

ShopSquire is an evidence-governed commerce decision platform that combines
forecasting, supply-chain intelligence, procurement workflows and bounded AI
agents without allowing model-generated text to become business authority.

That is a stronger and more defensible position than “an ecommerce chatbot.”
The differentiator is the separation of observations, evidence, hypotheses,
proposals, authorization and execution.

## What the demo should prove

The demo should make five claims, each backed by a visible artefact:

1. **Facts are governed.** Inventory, demand, supplier, market and conversation
   observations retain tenant, time, source, authority and provenance.
2. **Predictions are evaluated honestly.** Forecast comparisons preserve
   insufficient and undefined results, use rolling origins and show interval
   evidence rather than one unexplained number.
3. **Market claims require an exposure path.** A commodity movement or recall
   is not treated as SKU evidence unless a time-valid dependency path connects
   it to the product, supplier, facility, lane or cost structure.
4. **Agents are bounded.** Models may extract, classify, summarize and draft;
   deterministic services own facts, policy, money and execution authority.
5. **Outcomes are replayable.** Synthetic and operational events can be
   replayed to reproduce projections, decisions and counterfactual evaluation.

## Recommended 12-minute hiring-manager demo

### Minute 0–1: Frame the problem

Say:

> Most commerce AI demos generate persuasive text. ShopSquire focuses on the
> harder problem: deciding what the system is allowed to believe and do when
> inventory, suppliers, market signals and customer messages disagree.

State the limitations immediately: local/synthetic commerce history, three
credential-free public source families, and no claim of autonomous production
procurement.

### Minute 1–3: Forecast and replenishment evidence

Show the forecast comparison and explain:

- rolling-origin evaluation;
- lead-time demand rather than only next-day demand;
- seasonal naïve, EWMA, Croston/SBA and TSB;
- WAPE, MASE and bias;
- model-specific interval calibration;
- why insufficient and undefined are valid outcomes;
- why a forecast never directly creates a purchase order.

Then show a replenishment proposal and point to ATP, incoming supply, lead-time
uncertainty, MOQ, pack/UoM, price breaks and authority labels.

### Minute 3–6: Causal supply-risk workbench

Run one deterministic disruption scenario.

Show:

- the signal and its availability time;
- the time-valid dependency path;
- the bounded landed-cost or availability range;
- missing and contradictory evidence;
- alternative explanations;
- advisory versus simulation authority;
- bounded options such as monitor, request confirmation or seek a qualified
  alternative.

Change the scenario or seed and explain that product behaviour comes from
configuration dimensions rather than `if category == laptop` branches.

### Minute 6–8: Governed procurement

Open a procurement case and show the immutable context snapshot. Explain the
separation:

```text
observation -> evidence -> hypothesis -> proposal -> authorization -> execution
```

Show that supplier communication is a request for evidence, not an automatic
instruction. If using the security replay, demonstrate that a malicious reply
from a trusted supplier domain remains quarantined and cannot alter quote,
economics, purchase-order or payment state.

### Minute 8–10: Replay and engineering proof

Show:

- deterministic seed and generator version;
- append-only events plus corrections/reversals;
- inventory conservation and reconciliation results;
- simulation-only authority;
- focused test evidence and the isolated service-shard workflow;
- one migration upgrade/rollback/re-upgrade result.

Do not scroll through thousands of passing test dots. Show a small evidence
summary and one deliberately failing invariant followed by the corrected run.

### Minute 10–12: Architecture and trade-offs

Use one diagram:

```text
sources/messages
      |
      v
governed observations ---> quarantine/incomparable
      |
      v
identity + dependency graph
      |
      v
evidence bundle + bounded hypothesis
      |
      v
typed proposal ---> human/policy authorization ---> idempotent execution
      |
      v
outcome ledger + calibration
```

Finish with what remains unproven: real ERP reconciliation, live supplier
provider certification, hosted workflow proof until GitHub authentication, and
business lift on real cohorts.

## Evidence matrix for a portfolio review

| Capability | What to show | What it demonstrates | Honest boundary |
|---|---|---|---|
| Forecast intelligence | Rolling-origin comparison and interval report | Time-series evaluation, uncertainty and explicit undefined states | Synthetic/reconciled history is not design-partner history |
| Inventory projection | Event replay, custody balances and reconciliation | Event sourcing, corrections, transfers and deterministic read models | Cross-UoM and operational persistence must be proven by tests |
| Supply intelligence | Dependency path, signal provenance and alternatives | Grounded retrieval, causal restraint and PESTEL scope | Public signals remain advisory at SKU level |
| Procurement | Context snapshot, typed options and approval state | Domain modelling and bounded autonomy | No claim of fully autonomous purchasing |
| Supplier security | Quarantine reason and unchanged economic state | Adversarial AI/security design | External Gmail/M365 certification remains separate |
| Party intelligence | Timeline, impact preview and reversible redirect execution | Tenant-safe entity resolution, four-eyes authorization and governance | Split reverses a direct redirect; it does not repartition historical facts |
| Reliability | Durable jobs, retries, deadlines and shard diagnostics | Production-oriented distributed-systems thinking | Hosted infrastructure still needs direct proof |
| Legacy retirement | V2 compatibility boundary and shrinking imports | Safe strangler migration rather than rewrite theatre | Legacy file remains until characterizations move |

## Concepts you must be able to defend

### Forecasting

Be prepared to explain:

- rolling-origin versus random train/test splitting;
- why lead-time demand is the replenishment target;
- WAPE, MASE and bias, including undefined cases;
- intermittent demand and the differences between Croston, SBA and TSB;
- stockout-censored sales versus latent demand;
- prediction intervals versus confidence intervals;
- split-conformal calibration and its exchangeability limitation;
- why aggregate accuracy can conceal poor performance for intermittent,
  declining or newly launched items;
- why forecast accuracy and inventory decision utility are different metrics.

### Inventory and procurement

Know:

- on-hand, committed, ATP and incoming supply;
- safety stock and reorder-point assumptions;
- demand and lead-time variance;
- MOQ, case packs, price breaks and UoM comparability;
- landed cost, approved FX and inventory valuation;
- fill rate, OTIF, stockout cost, holding cost, waste and GMROI;
- why corrections and reversals must not rewrite accepted history;
- lifecycle gates such as sell-through, procurement-blocked and discontinued.

### Causal and market intelligence

Be able to distinguish:

- correlation, causal evidence and a supported hypothesis;
- an external market signal from proven product exposure;
- event time, publication time and evidence-availability time;
- a dependency graph from a generic vector-search result;
- source disagreement from genuinely incomparable measurement scopes;
- impact ranges from false point precision;
- observed outcomes from counterfactual policy estimates.

### Agent architecture

Explain why ShopSquire does not use one unrestricted “BrainAgent”:

- LLMs are useful for extraction, classification, summarization and drafting;
- deterministic code owns identity, arithmetic, policy and authority;
- tool calls need schemas, budgets, deadlines and idempotency;
- messages and retrieved text are observations, not instructions;
- proposals, approvals and executions are different durable records;
- escalation should depend on uncertainty, impact and policy;
- agent quality requires replayable evaluations, not impressive transcripts.

### Data and platform engineering

Know:

- tenant isolation and authoritative identity;
- append-only and bitemporal records;
- provenance, source licensing, revisions and retention;
- transactional outbox/inbox and at-least-once delivery;
- compare-and-swap cursors and idempotency keys;
- deadlines, retries, dead letters and stalled-job recovery;
- migration rehearsals and rebuildable read models;
- the difference between local, protocol, hosted and live-provider proof.

## Hard interview questions and defensible answers

### “Why synthetic data?”

Synthetic history is not evidence of business lift. It is used to test
invariants, known causal interventions, model discrimination, replay
determinism and failure behaviour before a design partner provides
authoritative history. Real performance claims require shadow evaluation on
real orders, inventory and supplier outcomes.

### “Is this mostly rules rather than AI?”

It is deliberately hybrid. Forecasting and statistical evaluation handle
demand; models extract and summarize unstructured evidence; deterministic
services enforce identity, calculations, policy and execution. Using an LLM
for arithmetic or authority would make the system less intelligent, not more.

### “How do you know the market signal caused the price change?”

The system does not claim that from the signal alone. It requires a governed
dependency path, compatible scope and time, supporting evidence, bounded
propagation assumptions and alternative explanations. Supplier confirmation
can strengthen a hypothesis, while invoices and receipts calibrate it later.

### “Is it production ready?”

Answer by capability. Local migrations, service shards and bounded contracts
have evidence. Real ERP reconciliation, external email-provider certification,
hosted workflow artefacts and measured commercial outcomes remain required.
Avoid a single unsupported yes/no claim.

### “What did you personally design?”

Answer with specific decisions and trade-offs:

- observation/proposal/authorization/execution separation;
- bitemporal and append-only evidence semantics;
- model-specific rolling evaluation;
- dependency-path grounding;
- simulation-only autonomy restrictions;
- threat-aware supplier communication;
- migration and legacy strangler strategy.

Then point to a commit, test or architecture decision for each claim.

## Further AI/ML improvements worth building

Prioritize improvements that increase calibration or decision quality:

1. Conditional interval calibration by intermittency, lifecycle, lead-time and
   disruption regime.
2. Hierarchical forecast reconciliation across SKU, variant, category and
   location without leaking future totals.
3. Explicit lost-demand and substitution estimation during stockouts.
4. Causal promotion and price-elasticity evaluation with pre-treatment checks,
   not correlations presented as uplift.
5. Forecast-value-added reports comparing each model and planner against
   seasonal-naïve and no-action policies.
6. Supplier reliability calibration with Brier/log scores and reliability
   diagrams rather than one opaque supplier score.
7. Evidence retrieval evaluation: dependency-path precision/recall,
   contradiction recall and unsupported-claim rate.
8. Agent action evaluation: tool-selection accuracy, abstention quality,
   authorization violations, timeout recovery and counterfactual regret.
9. Drift monitoring over data completeness, residuals, interval coverage and
   policy utility—not only input-feature distributions.
10. A design-partner shadow pilot with sealed predictions, controlled cohorts
    and a documented rollback criterion.

## Why this can support a hiring case

The strongest hiring signal is not the number of agents or repository size.
It is the ability to connect AI/ML, domain economics, security, data
governance and reliable execution while stating precisely what the evidence
does and does not prove.

Target roles where that combination matters:

- applied AI/ML engineer;
- agentic systems engineer;
- AI platform or backend engineer;
- decision-intelligence engineer;
- ML systems/product engineer;
- AI security engineer;
- supply-chain or commerce data scientist with strong engineering depth.

The closing message should be:

> I build AI systems that can explain which evidence they used, quantify when
> they are uncertain, abstain when facts are incomparable, and keep business
> authority outside model-generated text.

## Resume bullets that remain evidence-aligned

Adapt these to the role and only retain numbers you can reproduce:

- Designed a tenant-scoped, append-only decision-intelligence architecture
  separating observations, evidence, hypotheses, proposals, authorization and
  execution across forecasting, procurement and supplier-risk workflows.
- Built deterministic rolling-origin forecast evaluation for seasonal and
  intermittent demand, with explicit undefined states, model-specific interval
  evidence and simulation-only policy counterfactuals.
- Implemented a bitemporal supply-dependency graph that maps governed public
  signals to product exposure, preserves contradictory evidence and refuses
  unsupported SKU-level causal claims.
- Built rebuildable inventory projections covering transfers, quarantine,
  returns, disposal, corrections and reversals, with governed UoM conversion
  and fail-closed reconciliation.
- Implemented reversible Party identity resolution using impact previews,
  four-eyes authorization, graph-version conflicts and append-only redirect
  events without rewriting historical records.
- Stabilized 2,953 collected service tests across eight isolated local shards
  (2,952 passed and one optional live test skipped) with
  per-test deadlines and thread-leak diagnostics; distinguish this local proof
  from pending hosted and live-provider certification.

Avoid claims such as “increased revenue,” “reduced stockouts” or “production
ready” until a real design-partner cohort provides that evidence.

## Portfolio packaging checklist

Before sending the repository to a hiring manager:

1. Record one 8–12 minute video using the demo sequence above.
2. Put the architecture diagram and three evidence screenshots in the
   repository description or portfolio page.
3. Link to three small reviewable commits rather than asking the reviewer to
   understand the entire repository.
4. Be ready to open and explain one forecasting service, one governed workflow
   and one failure-oriented test without notes.
5. Show a red test or invariant, the defect it exposed and the green result.
6. Include the proof report generated by
   `scripts/run_ai_ml_portfolio_proof.ps1`, labelled with its commit.
7. State which code and design decisions you personally own. If AI-assisted
   tools contributed, explain how you reviewed, tested and constrained them.
8. Keep a one-page case study: problem, architecture, two hard trade-offs,
   evidence, limitations and next experiment.
