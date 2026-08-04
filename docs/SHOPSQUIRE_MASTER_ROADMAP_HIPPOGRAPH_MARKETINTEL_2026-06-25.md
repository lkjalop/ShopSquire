# ShopSquire — Master Roadmap: Hippograph + Market Intelligence + Extraction

**Date:** 2026-06-25
**Status:** Canonical execution plan. Consolidates four prior design docs into one sequenced roadmap.
**Supersedes/indexes:**
- `SHOPSQUIRE_MARKET_INTELLIGENCE_ADAPTIVE_GROWTH_IMPLEMENTATION_2026-06-25.md` (David deck → codebase map)
- `SHOPSQUIRE_ATTRIBUTION_BACKBONE_ARCHITECTURE_2026-06-25.md` (the loop)
- `SHOPSQUIRE_MERGED_ROADMAP_2026-06-25.md` (Copilot × Claude reconciliation, 5-phase)
- `SHOPSQUIRE_HIPPOGRAPH_INTELLIGENCE_SUBSTRATE_2026-06-25.md` (graph memory)

---

## 0. Where we are (banked, green)

The **measurement foundation is complete** — the thing every later phase stands on:

| Banked | Commit |
|---|---|
| Frontend↔backend parity gate (+ caught a real chat.py 500 bug) | `1111b2a` |
| Attribution agnostic core (record_decision / attribute_order / reward_from_outcome) | `b72ad6e` |
| Schema (recommendation_decision + conversion_event + orders.trace_id) | `4770455` |
| E0 capture → E1 carry → E2 close (loop) | `869d0dc`/`9dec0d1` |
| E3 reward feed (settled + quarantine, default-OFF) | `201eda7` |
| **E0 captures the REAL LinUCB arm (not A/B variant) via ContextVar** — fixed a reward-credit bug | `4847997` |
| Orchestrator increment 1: agent_budgets.py extracted | `88ffcde` |

**Net:** the recommender can now be measured and (when E3 is enabled) learns from revenue with the correct arm. ShopSquire already has **~75% of David's 7-module spine** (orchestrator = propose, policy gate + escalation = authorize, playbook = execute, decision-trace + audit chain = record). The work ahead is the missing 25% + making intelligence **compound** (the hippograph) + governed live execution.

---

## 1. The unified sequence (one plan, David's 5 phases × hippograph × extraction)

Extraction is **interleaved** — done only when a phase PR touches the seam, never "extract + add behavior" in one PR. The ratchets are the safety net.

### PHASE 0 — Measurement foundation ✅ DONE
Attribution capture+reward (correct arm), parity gate, agent_budgets. *Banked above.*

### PHASE 1 — Hippograph foundation + Visibility (David Phase 1) — **NEXT**
Build the compounding-memory substrate and turn on **read-only** market sight. Changes nothing customer-facing.
1. **`entity_resolution.py`** (agnostic core, additive) — canonicalize brand / product / user into stable entity ids. *The one genuinely-missing primitive; everything graph-y needs it.*
2. **`market_signal` envelope + ingestion** (internal sources only) — normalize consumer_signals / search_events / orders / returns / decision_trace / conversion_event into one schema (the integration contract). Each pipeline carries the deck's reliability checklist: schema-validate, freshness, retry, **trust-score**, dedup, timestamp-normalize.
3. **Graph projection read-API** — project `decision_trace_events` (already an edge table) + `conversion_event` (reward edges) + entity nodes into the existing `graph_retrieval` adapter (in-memory first, read-only). This *is* Module 2 (intelligence store).
4. **PPR / embedding recall** — top-k related entities seeded from the session, reusing pgvector + the trace graph. This *is* Module 3's recall leg.
5. **Visibility dashboards** — `trend_indicator` + conversion-by-arm/segment via `admin_bi` / `merchant_intelligence` (read-only).
6. **Cheap fix:** feedback endpoints (recommend.py:11668/11750) still read `"balanced"` — wire the same `get_bandit_arm()`.

### PHASE 2 — Advisory (David Phase 2)
Analyze + decide, but **log only** — prove a change *would* have helped before it touches anyone.
1. **Market Analysis Engine (M3):** *wrap* existing AnomalyDetector + DemandForecaster; *add* objection-theme classifier (`support_theme_summary`), messaging-fatigue, competitor-undercut detector (stub feed).
2. **Decision Engine (M4) SHADOW:** bounded decisions via the **existing** `action_authority_matrix` + `escalation_policy` (don't build parallel) — logged + compared to actuals via Phase-1 attribution (the proven shadow/parity pattern).
3. **Hippograph feedback injection (advisory-OFF):** `hippograph_insights` → Redis `kv_state` + new `NQEInput.hippograph_context` + trace events. **H2A consolidation edges:** approvals / NQE-feedback / escalation become high-trust graph edges (agents learn from human corrections).

### PHASE 3 — Experiment + rollback (Module 6b — the "non-negotiable")
`experiment_run` / `experiment_assignment` / `experiment_result` + uplift calculator + rollback trigger. The bandit becomes one assignment strategy. **Adopt the anti-false-positive (seasonal lift not credited) + anti-Goodhart (clicks↑ margin↓ → revert) tests.** This earns the *right* to go live.

### PHASE 4 — Low-Risk live adaptation (David Phase 3)
Turn on **reversible** nudges only (ranking, support phrasing, retargeting) — each gated by experiment+rollback + a new **`contact_frequency_ledger`** + the kill switch. Extend M7 (marketing action allowlist + region rules).

### PHASE 5 — Bounded optimization (David Phase 4) — partly external-blocked
Offer/bundle engine, inventory-aware campaign suppression, **competitor price feed** (needs creds), **ESP/SMS push** (needs SendGrid/Klaviyo + SPF/DKIM/DMARC). Build interfaces now, wire when keys arrive.

> **Phase 5 (David) = Closed-Loop Growth** is the union of all the above running continuously under full policy control — not a separate build.

---

## 2. Leverage the hippograph properly — the compounding loop

The hippograph is **not a new database** — it's a unification + entity-resolution + recall service over substrate you already run (Neo4j, pgvector, `decision_trace_events`, Redis episodic, GNN). The reward edge it ranks *toward* is now built (`conversion_event`).

**The loop:**
```
ingest (market_signal) → entity-resolve (canonical nodes) → project (trace + reward + entity → graph)
→ PPR/embedding recall (top-k related, seeded by session entities) → inject (hippograph_insights into
agent context) → act → outcome (conversion_event = reward edge) → consolidate (H2A: approvals /
NQE-feedback / escalation = high-trust edges) → [the graph is now smarter for the next query]
```

**What "leverage properly" requires (in order):**
1. **Entity resolution** (Phase 1.1) — without canonical nodes the graph can't compound ("Dell"/"DELL"/"xps-123" must be one node).
2. **Reward edges** ✅ — `conversion_event` is what PPR ranks toward (done).
3. **Read-only projection** (Phase 1.3) — prove the latent graph before persisting.
4. **Recall + injection** (Phase 1.4 → 2.3) — the 19 injection points (agent `kv_state`, `NQEInput.hippograph_context`, scratchpad, AgentBus payload, trace WS, dashboards) — advisory-OFF until bench.
5. **Consolidation edges** (Phase 2.3) — human feedback is the highest-trust signal; weight it.
6. **Neo4j persistence** — only when multi-hop becomes hot-path (Phase 4+).
7. **Governance:** every insight that *acts* re-enters policy gate → escalation → kill switch → audit chain. Hippograph **proposes; never executes.**

---

## 3. Data sources to improve agentic intelligence & behaviour

The deck's thesis: *bad input → bad autonomous behaviour.* Every source carries trust-scoring + quarantine (we already do this in `demand_forecast` + attribution reward). What each source *improves*:

| Source | Int/Ext | Status | Improves which agent / behaviour |
|---|---|---|---|
| `conversion_event` (attribution reward) | internal | ✅ built | Ranking/bandit **learns what converts** (the reward) |
| Entity graph (hippograph) | internal | Phase 1 | Every agent reasons over canonical entities + **prior outcomes** |
| clickstream / `consumer_signals` | internal | flows | Demand + intent signals; cart-abandonment → retargeting agent |
| `search_events` | internal | flows | Query trends → demand-aware ranking |
| orders / returns | internal | flows | Margin/return-risk → decision engine, return-prevention guidance |
| `support_theme_summary` (objections) | internal | Phase 2 | **Support agent adapts phrasing**; objection→guidance updates |
| sentiment (reviews/support) | int/ext | Phase 2 | **Copywriting/narration tone**; messaging-theme classification |
| `segment_definition`/membership | internal | Phase 2 | **Personalization** + segment-aware NQE/offers |
| `trend_indicator` | internal | Phase 1 | Demand-aware ranking + inventory suppression |
| `channel_performance` | internal | Phase 4 | Channel routing/prioritization agent |
| message/campaign performance | internal | Phase 3 | Comms optimization; messaging-fatigue detection |
| `decision_outcome` | internal | Phase 2 | **Ground truth** — analysis engine validates past decisions |
| **H2A edges** (approvals/NQE-feedback/escalation) | internal | Phase 2 | Agents learn from **human corrections** (RLHF-like consolidation) |
| `competitor_snapshot` (price feeds) | **external** | Phase 5 (creds) | Competitor-undercut response; bundle-vs-discount decisions |
| trend/keyword demand feeds | **external** | Phase 5 (creds) | Early category-interest detection |
| category benchmarks, macro/seasonal | **external** | Phase 5 | Seasonality + anti-false-positive attribution |

**Reliability is a first-class control** (deck Step 5): every pipeline must schema-validate, freshness-check, retry, **trust-score**, dedup, timestamp-normalize — and quarantine suspect signals (already the pattern). This is what stops bad data from poisoning agent behaviour.

---

## 4. Extraction / excision ledger

| File | Lines | Action | When |
|---|---|---|---|
| `routers/recommend.py` | 11,980 | continue strangler (23 modules out); keep E0 seam clean; lower flavour ratchet | ongoing/opportunistic |
| `services/orchestrator.py` | 4,009 | ✅ budgets out (88ffcde); proposal arm-stamp solved via ContextVar; **defer** phase-file moves (no longer block hippograph) | when a PR touches it |
| `security/email_security.py` | 5,108 | split monolithic `evaluate_email` → orchestrator + stages | when M3 objection/sentiment touches it |
| `routers/merchant_dashboard.py` | 3,488 | extract ~1.8k inline HTML email-lab → templates | when dashboards get market-intel panels (Phase 1.5) |
| `routers/admin.py` | 4,168 | defer (flags/policy/BI mix) | only if touched |
| `routers/support_complaints.py` | 3,990 | extract threat-matrix only if needed | defer |
| `recommendations.py` (2,223), `decisions.py` (2,565), `escalation_room` (1,936), `playbook_engine` (1,767) | — | **leave alone** (good cohesion) | — |

Guardrails hold throughout: `test_no_flavour_in_core` (ratchet down only), `test_no_silent_except_in_core`, `test_profile_parity`, the parity gate, and `test_recommend_contract_stability` as the behavioral net.

---

## 5. What's left from David's deck (gap-closure checklist)

| Module / Step | Exists | Concrete remaining build | Bound |
|---|---|---|---|
| **M1 Signal Ingestion** | internal events flow | `market_signal` envelope + reliability checklist; external feeds=stub | trust-score + quarantine |
| **M2 Intelligence Store** | decision_trace/logs, pgvector, Redis | `trend_indicator`, `competitor_snapshot`, `segment_*`, `channel_performance`, `support_theme_summary` (= the hippograph) | bitemporal + retention |
| **M3 Analysis Engine** | AnomalyDetector, DemandForecaster | *wrap* + add objection/fatigue/competitor/sentiment classifiers | min-sample gate |
| **M4 Decision Engine** | `action_authority_matrix`, `escalation_policy` | bounded messaging/support/campaign/segment decisions (reuse, shadow-first) | authority bands |
| **M5 Comms Orchestrator** | recommend ranking, NQE, retargeting, SendGrid | storefront banner/hero, support-phrasing, marketing execution **adapters** (templates only) | reversible-only first; ESP=creds |
| **M6 Experiment & Attribution** | **attribution ✅**, LinUCB bandit | `experiment_run/result` + uplift + rollback + anti-false-positive/anti-Goodhart tests | rollback threshold |
| **M7 Policy/Governance/Audit** | policy gate, audit chain, replay, claim guard, kill switch | **`contact_frequency_ledger`**, region/channel rules, marketing action allowlist | fail-closed |
| Step 5 reliability | safe_stage, quarantine | the per-pipeline checklist as a shared validator | — |
| Step 10 recovery | safe_stage, fallback, exception_resolver | wire "revert to last safe strategy" for live actions | autonomous outcomes |
| Step 11 observability | status_summary, admin_bi | signal/decision-state + experiment-health + policy-block-rate panels | owner-not-runtime |

**Design principle (deck p15) — already ShopSquire's spine, keep it:** *AI interprets & proposes. Policy authorizes. Automation executes. Audit records.* And LLM output must **never** directly trigger privileged actions (we enforce via claim guard + policy gate).

---

## 6. Immediate next actions (updated 2026-06-25 after GPT-5.5 review + operational hardening)
Phase 1 (hippograph foundation + feedback) and Module 1 (envelope + adapters) are **landed**; GPT-5.5
flagged wiring gaps which are now closed (`d02c8ef` task registration + market_signal indexes/freshness;
`ba4139b` NQEInput injection + recall kind-filter + trace event). Updated next order:

1. **M3 narrow baseline** — typed `market_finding` contract + 3 detectors (demand shift, conversion
   anomaly, inventory-demand mismatch) over `market_signal` windows, **reusing AnomalyDetector +
   DemandForecaster** (no LLM for finding generation). The next real value step.
2. **Project findings into the hippograph** — findings become `finding` nodes (already allow-listed in
   recall) with typed edges (`indicates` / `blocked_by` / `converted_after` / `returned_after` /
   `corrected_by_human`); add NEGATIVE outcomes (not only conversion reward) + temporal decay + tenant
   isolation.
3. **Bench the flags** — `HIPPOGRAPH_FEEDBACK_ENABLED` + `MARKET_SIGNAL_BACKFILL_ENABLED` in a
   controlled run; measure recall quality + signal volume before any agent *consumes* findings.

Deferred (do when M3 needs them): market_signal quarantine-status persistence + tenant/schema-version
columns (migration); hippograph recency/trust/relationship-type weighting; more source adapters
(inventory, supplier, returns, support objections, sentiment, competitor). Experiment + rollback
framework remains the gate BEFORE any finding affects ranking/messaging (no live adaptation until then).

Everything stays measurement-first → autonomy-last → every step auditable.
