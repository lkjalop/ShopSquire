# ShopSquire — Merged Roadmap (Copilot × Claude reconciliation)

**Date:** 2026-06-25
**Inputs:** GitHub Copilot's "Remaining Work + Marketing Intelligence Backbone" plan (Tiers 1.2/2.3/4.2/5 + David's 7 modules) and Claude's attribution-backbone deep dive (`SHOPSQUIRE_ATTRIBUTION_BACKBONE_ARCHITECTURE_2026-06-25.md`).
**Purpose:** one ordered plan, what's needed, what changed and why, and the business outcome each phase unlocks.

---

## The one disagreement that reorders everything

Copilot makes **"Module 6 — Experimentation & Attribution"** a single step-2 block: new `experiment_run` / `experiment_assignment` / `attribution_event` / `experiment_result` tables **plus** an uplift calculator with p-values **plus** a rollback trigger — 4–5 sessions.

But the deep dive showed the **attribution *capture* loop is ~60% latent** (the write primitive `record_commerce_outcome` exists at `decision_log.py:1033`; `recommend_interactions` already has `trace_id`; the IDs converge at `recommend.py:10238`). And you **cannot compute uplift / p-values / rollback until attributed conversions are flowing.**

> **So split M6 into M6a (capture) and M6b (experiment framework).** M6a is one small PR and is the literal prerequisite for M6b. Copilot conflated them; separating them turns a 5-session block into a 1-PR keystone that immediately produces value, with the heavier stats framework arriving only when there's data to feed it.

Everything else follows from sequencing autonomy behind measurement — which is exactly what David's 5-phase rollout demands.

---

## The merged sequence (do in this order)

| # | Phase | What | Merges (Copilot / Claude / David) | Effort | Business outcome |
|---|---|---|---|---|---|
| **0** | De-risk the measurement path | Convert the silent-fails **on the attribution path only** (retrieval, ranking, the capture seam) — a *subset* of Copilot Tier 1.2 batch 2 | Copilot T1.2 (narrowed) | ~1 sess | Trustworthy measurement; kills the ASUS-grounding silent-drop bug class on the path you're about to measure |
| **1** | **Attribution CAPTURE (keystone)** | `recommendation_decision`+`conversion_event` tables, `orders.trace_id`, core `services/attribution.py`, wire E0/E1/E2; read-only conversion-by-arm dashboard. **Capture default-ON, measurement only** | Claude M6a / Copilot M6 (first half) / David Phase 2 enabler | ~1–2 sess | **Every recommendation becomes measured.** Demo-able "$X order traced to this rec." Foundation for every optimization claim |
| **2** | Close the learning loop, safely | E3 reward feed (Celery, **settled-orders + quarantine**), fixes the undefined bandit reward. **Default-OFF until bench-validated** | Claude E3 / Copilot M6 bandit wiring | ~1–2 sess | The recommender **learns from revenue**, not guesses; margin-aware ranking becomes possible |
| **3** | **Visibility** (David P1) | Signal ingestion + intelligence store from **internal** events → `market_signal` schema → `trend_indicator` + dashboards. Competitor adapter = STUB | Copilot M1+M2 / David Phase 1 | ~3 sess | **Merchant sees the market move** — demand trends, conversion drops, inventory-demand misalignment — before losing the sale |
| **4** | **Advisory** (David P2) | Analysis engine (**wrap** AnomalyDetector + DemandForecaster + new objection/fatigue classifiers) + decision engine **SHADOW-only** (via `action_authority_matrix` + escalation bands), compared to actuals via Phase-1 attribution | Copilot M3+M4 (shadow) / David Phase 2 | ~4 sess | **"The system would have done X — and it would have helped/hurt,"** proven before any live change |
| **5** | Experiment + rollback framework | `experiment_run/assignment/result` + uplift calculator + rollback trigger; bandit becomes one assignment strategy. **Adopt Copilot's anti-false-positive (seasonal) + anti-Goodhart (clicks↑ margin↓→revert) tests** | Copilot M6 (second half) / Claude M6b / David Phase 2→3 gate | ~3 sess | **The license to go live** — prove a change helped + auto-revert. The safety net the deck makes non-negotiable |
| **6** | **Low-Risk Adaptation** (David P3) | Turn on **reversible** nudges only (ranking, support phrasing, retargeting), each gated by experiment+rollback+`contact_frequency_ledger`+kill-switch. M7 marketing action allowlist + region rules | Copilot M5(reversible)+M7 / David Phase 3 | ~3 sess | **First revenue lift from autonomous adaptation** — reversible, measured, bounded |
| **7** | **Bounded Optimization** (David P4) | Offer/bundle engine, inventory-aware campaign suppression, competitor feed, marketing push | Copilot M5(marketing) / David Phase 4 | ~4 sess (partly blocked) | **Margin-preserving growth engine** — bundles before discounts, suppress demand on low-stock, competitor response |
| **∥** | **Interleaved: god-file extraction** | Extract a seam **only when a phase PR touches it** (orchestrator arm-stamp in P1; retriever extraction = Copilot T2.3 in P3/P4; main.py hygiene anytime; Tier 4.2 adapter migration when a 2nd vertical ships) | Copilot T2.3/T4.2/T5 | ongoing | Velocity + reliability; shrinks the monolith without a value-delaying detour |

**Blocked on external credentials (Copilot's "skip" — agreed):** competitor price feed (P7), ESP/SMS push + SPF/DKIM/DMARC domain auth (P7), live outbound campaigns. Build the STUBs + interfaces now; wire when keys arrive.

---

## What I'd change about Copilot's plan (and what I'd keep)

**Change:**
1. **Split M6.** Capture (1 PR) before the experiment/uplift framework (3 sessions). You can't compute uplift without attributed conversions. This is the single biggest reorder.
2. **Reuse the spine; don't build parallel packages.** Copilot proposes new `market_decision/`, `market_analysis/` from scratch. M4 should be `action_authority_matrix` + `escalation_policy` (they already do bounded authority bands); M3 should *wrap* `AnomalyDetector`/`DemandForecaster`; M7 should *extend* the existing policy/audit, not add a parallel one. ShopSquire already has ~75% of the spine — extending it is faster and inherits the audit chain + replay for free.
3. **Narrow Tier 1.2 batch 2.** Don't do all 25 silent-fail conversions as a 3-session prelude. Do the ~8 on the attribution path first (Phase 0); convert the rest opportunistically when a PR touches that file. Don't let mechanical hygiene delay the first business value.
4. **Defer standalone extractions (Copilot's 5.1/5.2 at steps 3–4).** They're good hygiene but not on the critical path to value. Interleave extraction only when a feature PR naturally opens that seam — never "add behavior + extract" in one PR.
5. **Gate M5 *live* execution behind M6b (Phase 5), not just behind capture.** Copilot builds M5 executors at step 9; ensure live push is gated by experiment+rollback, not just attribution capture. Otherwise you've built the "confidently make things worse" machine the deck warns against. (Reversible nudges in P6 are fine; offers/campaigns wait for P7.)
6. **Add the missing primitives early:** the `market_signal` schema (the integration contract both attribution and M1 write into — decide it in Phase 1), the **settled-order/returns window** for reward integrity (Copilot's `attribution_event` omits it), and `contact_frequency_ledger` (both plans list it — land it in P6).

**Keep (Copilot got these right):**
- Silent-fail-first instinct (de-risk before measuring) — I just narrowed it.
- The blocked-external honesty (competitor feed / ESP keys) — correct and explicit.
- **The M6 test design is excellent** — especially the **anti-false-positive** (a seasonal lift with no causal variant change must not be credited) and **anti-Goodhart** (a variant that lifts clicks but drops margin → terminal decision `revert`) tests. Adopt verbatim into Phase 5.
- Reuse notes for M3 (wrap existing detectors) and M7 (reuse + extend) — directionally right; I'd push harder on the same for M4.
- The strict dependency ordering for Tier 5 (constraint engine last, ContextVars drop only after stages take explicit dataclasses).

---

## What's needed (prerequisites & decisions)

- **No blockers** for Phases 0–6 (all internal signals + existing infra).
- **External creds** (Phase 7 only): competitor feed, ESP (SendGrid/Klaviyo) + SMS keys, SPF/DKIM/DMARC. Build interfaces now.
- **Schema decision (Phase 1):** the `market_signal` common envelope — it's the contract attribution + M1 + M3 all share. Propose + lock before P3.
- **Standing safety constraints (carry through all phases):** learning/reward feed default-OFF until bench-validated; supplier comms draft-only (SUP-04 HUMAN_REVIEW); every action re-enters policy gate → escalation bands → kill switch → audit chain; `uid_hash` only (no raw PII); attribution measures & proposes, never executes.
- **The one prioritization call (yours):** does this program run **now**, or **after** the in-flight demo-readiness / Playwright track? Recommendation below.

---

## Business outcomes, in plain terms

- **Phase 1 (capture):** you can finally say *"this recommendation drove this order"* — the recommender stops being a black box and becomes a measured revenue surface. Strong demo/sales artifact on its own.
- **Phase 2 (learning loop):** the recommender optimizes for **revenue and margin**, not clicks — directly lifts conversion and AOV over time.
- **Phase 3 (visibility):** the merchant sees demand/competitor/conversion shifts early — fewer lost sales to stockouts and missed trends.
- **Phase 4–5 (advisory + experiment):** you earn the **right to automate** — every autonomous change is proven (uplift) and reversible (rollback) before it touches a customer.
- **Phase 6–7 (live adaptation):** the actual **autonomous growth engine** — adaptive storefront/messaging/offers that lift revenue while *preserving margin* (bundles before discounts) and *protecting inventory* (suppress demand on low stock).
- **Throughout (extraction):** faster, safer iteration; the silent-fail bug class (wrong/empty recommendations) shrinks — which protects the conversion you're now measuring.

The through-line: **measurement first, autonomy last, every step auditable** — which is both the safest path and the one that produces a demoable business artifact at Phase 1 instead of Phase 9.

---

## Recommended immediate next step

Run **Phase 0 + Phase 1 as one focused effort**: narrow silent-fail hardening on the attribution path, then ship the capture loop (migration + `services/attribution.py` + E0/E1/E2, capture default-on, reward default-off). It's low-risk, internally unblocked, and turns your already-shipping recommendations into a measured system — the foundation everything above stands on. Hold Phase 2's reward feed behind its flag until the quarantine controls are bench-validated.
