# ShopSquire — Intelligence Integration Architecture

**Date:** 2026-06-25
**Context:** The closed loop now exists end-to-end (events → market_signal → M3 findings → hippograph →
gated reversible nudge → measure → auto-revert). This doc is the **integration plan**: how that loop
threads through the hippograph, the agentic swarm, scatter-gather, external search, query
decomposition, and the large-file extraction — agnostic-first, with explicit "when to leverage" gating.

Principle throughout (deck p15): **AI interprets & proposes · Policy authorizes · Automation executes
· Audit records.** Market intelligence is firmly in *interpret/propose*; it only acts through the
experiment gate, and only when a query *needs* it.

---

## 1. The join key is `trace_id`; the memory is the hippograph

Everything already shares one spine — the **decision trace** (`decision_trace_events`, an edge table)
keyed by `trace_id`. Attribution, findings, recall, and the nudge all hang off it. So integration is
*not* new plumbing; it's enriching the trace + the hippograph that projects from it.

```
                         ┌──────────────── hippograph (unified memory) ────────────────┐
events → market_signal → M3 findings ─┐                                                │
decision_trace_events ───────────────┼─→ project_graph + project_findings → recall/PPR ┘
conversion_event (reward) ────────────┘                          │
                                                                 ▼
                                            hippograph_insights (advisory) → agents / dashboards
                                                                 │  (only via experiment gate)
                                                                 ▼
                                                  reversible ranking nudge (treatment-only)
```

---

## 2. Agentic swarm + scatter-gather integration

The orchestrator runs EXPLORE → EVALUATE → PLAN → ACTION with parallel agents (`asyncio.gather`).
Integration is **one new EXPLORE-phase gather leg + context injection**, no new control flow:

- **New `Market_Intelligence_Agent` (EXPLORE, read-only):** runs *in parallel* with retrieval (it's a
  ~0.1 ms recall + a findings lookup — cheap), and writes `hippograph_insights` + relevant findings
  onto the shared proposal/blackboard. It proposes context, never actions (re-enters policy if it ever
  did). This is a scatter-gather *leg*, not a serial stage — it never blocks the main path.
- **Agent context feed:** each downstream agent reads the market context from the blackboard —
  `NQEInput.hippograph_context` is already wired; the ranking agent reads finding-annotated entities
  ("demand spike in this category", "this SKU historically converts for this segment").
- **Adaptive budgets react to findings:** `agent_budgets.compute_adaptive_agent_budgets` already takes
  `event_signals`; feed it finding signals (e.g., a `competitor_undercut` finding → boost the
  ranking/pricing agent's budget; a `support_objection` finding → boost the support agent). Vertical-
  blind: the agent names + boosts are agnostic; the *finding types* come from the profile-tuned M3.
- **A2A / consolidation edges:** `AgentBus` hand-offs + human feedback (approvals / NQE-feedback /
  escalation) become **typed high-trust edges** in the hippograph (`corrected_by_human`), so the swarm
  learns from corrections — the highest-trust signal.

---

## 3. External search → competitor intelligence (agnostic, guarded)

External search (`external_research_httpx`, SSRF-guarded, allowlisted, PII-scrubbed, disabled-by-
default) is the **competitor/trend data source**. A new `competitor_adapter` normalizes an allowlisted
price/promo result into a `market_signal(signal_type="competitor", source="external_research", …)` with
a **low trust score** (external + unverified) so the trust-gate can quarantine it. M3 then detects
undercutting → `competitor_undercut` finding → hippograph. Nothing external ever enters the cart or
acts directly; it produces a finding that re-enters the gate. *Phase 5 / needs allowlisted feeds.*

---

## 4. Better query decomposition = the agnostic "WHEN to leverage"

This is the crux of *when* to spend the market-intel cost. Extend `QueryPlan` (query_decomposer) with
**`needs_market_evidence`** + `evidence_requirements` (GPT's suggestion), set deterministically from
query semantics — not a vertical list:

| Query shape | needs_market_evidence | Why |
|---|---|---|
| "what's trending / popular / best-selling / hot right now" | **yes** (demand/trend) | wants market state |
| comparison / "is X worth it" / "should I wait" | **yes** (competitor/historical-outcome) | wants evidence |
| bulk / B2B / "for my fleet" | **yes** (demand + supply) | wants availability/demand |
| a specific product lookup, a support question | **no** | constraints + product fit suffice |

Only when `needs_market_evidence` does the swarm run the `Market_Intelligence_Agent` + inject findings
— so simple lookups never pay the cost. The decomposer mechanism stays agnostic (it keys on intent
verbs/structure); vertical vocabulary that maps to those intents lives in the profile.

**Narration priority (unchanged, enforced):** `user constraints > product fit > inventory truth >
historical outcomes > market trend`. Market popularity must NEVER override suitability — findings
annotate, the claim guard still grounds every claim.

---

## 5. Data sourcing — agnostic, trust-scored, never-acts

| Source | Int/Ext | Status | signal_type |
|---|---|---|---|
| orders / conversions / search | internal | ✅ adapters live | order / conversion / demand |
| inventory + supplier lead-time | internal | adapter TODO | inventory / supply |
| returns / refunds | internal | adapter TODO (enables real guardrails) | return |
| support objections + sentiment | internal | adapter TODO | support_objection / sentiment |
| competitor price/promo | **external** | adapter TODO (Phase 5) | competitor |
| trend/keyword, category, seasonal | **external** | adapter TODO (Phase 5) | trend |

Agnostic rule (already enforced): every source → the **one `market_signal` envelope** (opaque
type/source/payload) with the deck's reliability checklist (schema-validate, freshness, **trust-score**,
dedup, timestamp-normalize). The **returns adapter is the highest-value next** — it unlocks a *real*
anti-Goodhart guardrail (return-rate per variant) for the experiment evaluator, which today runs on
uplift alone.

---

## 6. Large-file extraction — pay it down where the integration lands

The intelligence code is all **new agnostic core modules** (clean, ratcheted). The integration touches
two god-files; extract exactly the seams it opens, never more:

- **`recommend.py`** — the three injection blocks I added (E0 capture, hippograph feedback, ranking
  nudge) plus external research should consolidate into **one extracted `recommend_intelligence_stage.py`**
  (a single post-results stage: capture → recall → nudge), tested in isolation. This stops recommend.py
  bloating and makes the intelligence path a unit.
- **`orchestrator.py`** — adding the `Market_Intelligence_Agent` to EXPLORE is the natural moment to do
  the deferred **phase-file split** (`orchestrator_phase_explore.py`), extracting that phase + the new
  agent together. Budgets are already extracted (`agent_budgets.py`).
- Rule holds: extract only the seam a PR touches; never extract + add behavior in one PR; ratchets
  down-only.

---

## 7. Where it all stays bounded

- **Advisory by default** — every new field/effect is flag-OFF; the parity gate asserts absence.
- **Gated execution** — a finding only changes ranking via the experiment gate (treatment + live), and
  the evaluator **auto-reverts** losers/guardrail-breachers.
- **Auditable** — every step emits a trace event; the hippograph + decision log are replayable; the
  audit chain is tamper-evident.
- **Agnostic** — mechanisms in core (no-flavour ratchet), tuning in the StoreProfile; the decomposer's
  `needs_market_evidence` keys on intent, not vertical vocabulary.

---

## 8. Recommended execution order (next)
1. **`query_decomposer.needs_market_evidence`** — the agnostic "when" gate (additive field + intent
   rules). Cheap, unblocks targeted leverage.
2. **`Market_Intelligence_Agent` in EXPLORE** (read-only gather leg) + extract `orchestrator_phase_explore.py`.
3. **Consolidate `recommend_intelligence_stage.py`** (the three injection blocks → one tested stage).
4. **Returns adapter** → real anti-Goodhart guardrail for the evaluator.
5. Then breadth: more adapters, typed-edge relations, temporal decay, tenant isolation, dashboards,
   Phase 4 (offers/bundles/campaigns).
