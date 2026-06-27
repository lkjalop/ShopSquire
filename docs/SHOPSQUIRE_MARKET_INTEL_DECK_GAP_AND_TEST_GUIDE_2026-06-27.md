# Market Analysis & Adaptive Growth — Deck Gap Analysis + E2E Test Guide
**2026-06-27** · maps David's deck (7 modules · 11 steps · 5 phases) to the codebase, lists what's left, and gives the exact test prompt, files, browser clickthrough, and delta-progression test.

---

## A. Deck → codebase status

### The 7 modules
| # | Module (deck) | Status | Where it lives |
|---|---|---|---|
| 1 | **Signal Ingestion** | ✅ **Done** | `market_signal.py` (envelope: schema-validate · trust-score · dedup · freshness · timestamp-norm) + `market_signal_adapters.py` (orders/conversion/search/returns from real tables, idempotent backfill; + competitor/support-objection/funnel). |
| 2 | **Market Intelligence Store** | ⚠️ **Partial** | `market_signal` + `market_finding` tables (dual-mode: signals live, findings persisted); `price_book_entry`/`inventory_level`/`competitor_observation`/`support_objection`/`cart_funnel_event`. **Missing:** `trend_indicator`, `segment_definition/membership`, `message_variant/campaign_variant/offer_policy`, `channel_performance`, `customer_intent_signal`, `support_theme_summary`, warehouse sink. |
| 3 | **Analysis Engine** | ✅ **Mostly done** | `market_analysis.py` — **8 detectors**: demand_shift · conversion_anomaly · inventory_demand_mismatch · demand_forecast · seasonal_demand · competitor_undercut · objection_cluster · funnel_dropoff. Toolkit: deterministic rules ✅, time-series forecast (EWMA + `DemandForecaster` ARIMA/Prophet) ✅, anomaly detection (`AnomalyDetector`) ✅. **Missing:** trained classifiers (objection clustering is keyword-based; intent/return-risk/segment-propensity not built), summarization-LLM trend digests. |
| 4 | **Decision Engine** | ⚠️ **Partial** | `shadow_actions.py` (findings→typed proposals, **log-only**): demand→adjust_ranking, conversion/**objection/funnel**→revise_support_copy, inventory→suppress_low_stock. Eval criteria via `adaptive_action_gate` (confidence+policy+reversibility) + `economics` (margin) + `inventory_source`. **Missing:** campaign pause/activate from findings; **segment decisions** (no segment model). |
| 5 | **Communication Orchestrator** | ⚠️ **Partial** | Storefront: `ranking_nudge` (recommendation ranking) **live behind the experiment gate**. Support: `template_phrasing` (tone variants) — proposed, not live-executed. Marketing: `campaign_governance` (readiness + dispatch planner) — governed, but live email/SMS/retargeting is **SANDBOX** (Phase-8 transports). **Missing:** banners/hero/landing execution; live support-guidance push; live marketing send. |
| 6 | **Experimentation & Attribution** | ✅ **Strong** | `experiments.py` (assign/uplift/decide anti-Goodhart) + `experiment_eval.py` (**auto-revert**) + `attribution.py` (decision→conversion, post-assignment window) + `experiment_console.py` (operator promote/observe/evaluate/revert). A/B · control/treatment · attribution windows · uplift · rollback triggers. |
| 7 | **Policy / Governance / Audit** | ✅ **Strong** | `adaptive_action_gate.py` (confidence+authz+durable audit, **fail-closed**) + `contact_governance.py` (consent/frequency/region) + `campaign_governance.py` + `decision_log` + audit chain + `maestro_boundaries`. Action boundaries · contact/region caps · confidence thresholds · immutable logging/replay. |

### The 5 phases
| Phase | Deck | Status |
|---|---|---|
| 1 · Visibility Only | ingest + store + dashboards | ✅ market pipeline + operator **Market Intelligence** tab |
| 2 · Advisory Mode | propose + score + log, no live exec | ✅ `shadow_actions` log-only proposals |
| 3 · Low-Risk Adaptation | homepage/landing/support-phrasing/**recommendation-ranking** | ✅ `ranking_nudge` live behind experiment gate + console; support-phrasing **proposals** wired |
| 4 · Bounded Optimization | approved offers/bundles/segment-campaigns/channel/inventory-suppression | ⚠️ **Partial** — governance scaffold (`campaign_governance`); offer/bundle/segment/channel **execution not built** |
| 5 · Closed-Loop Growth | continuous across **all** channels | ⚠️ **Partial** — closed loop proven for ranking; not across all channels |

**Bottom line: Phases 1–3 substantively DONE; the safety spine (M6–M7) is the strongest part. The remaining build is Phase 4–5 — segments, offers/bundles, campaign execution, channel performance — plus trained classifiers and the warehouse.**

---

## B. What's left from the PDF (prioritized)

1. **Segments** (M2/M4, Phase 4) — `segment_definition` + `segment_membership` + propensity scoring → segment decisions ("increase comms to high-intent segments within frequency caps"). *Nothing built.*
2. **Offers / bundles / campaign execution** (M4/M5, Phase 4) — `message_variant`/`campaign_variant`/`offer_policy` tables + the decisioning that activates/pauses them. `campaign_governance` is the gate; the *content + execution* is the gap.
3. **Channel performance + prioritization** (M2/M4) — `channel_performance` table + channel routing decisions.
4. **Trained classifiers** (M3) — intent detection, return-risk, segment propensity, message-theme — replace the keyword `objection_cluster` with a model.
5. **Summarization-LLM trend digests** (M3) — "summarize support/review trends; generate approved copy variants" (within policy; LLM never directly triggers privileged actions — already the design rule).
6. **Warehouse sink + derived-feature layer** (Step 4) — `market_signal` → columnar warehouse for historical/seasonal training.
7. **Live marketing/support transports** (M5, Phase 8) — real email/SMS/support-guidance push (the SMTP/PO seams exist; support/marketing transports don't yet).
8. **Exception/recovery paths** (Step 10) — most exist (quarantine, fall-back-to-rules, suppress, revert); audit there's **no unresolved "a human will fix it"** path per signal source.

---

## C. Exact tests to run (the automated regression spine — all green today)

```bash
# from repo root (IMPORTANT — ratchet tests use cwd-relative paths):
Set-Location C:\AI\ShopSquire ; $env:PYTHONPATH="C:\AI\ShopSquire"

# Module 1 — ingestion
pytest tests/services/test_market_signal.py tests/services/test_market_signal_adapters.py
# Module 3 — analysis engine (8 detectors)
pytest tests/services/test_market_analysis.py
# new live sources (competitor / support-objection / funnel) + their migrations
pytest tests/services/test_competitor_source.py tests/services/test_support_objection_source.py \
       tests/services/test_funnel_source.py tests/test_competitor_observation_migration.py \
       tests/test_support_objection_migration.py tests/test_cart_funnel_event_migration.py
# real pipeline (ingest→analyze→persist, tenant-clean) + synthetic replay
pytest tests/services/test_market_pipeline.py tests/services/test_market_replay.py
# Module 4 — decision engine (shadow proposals, log-only)
pytest tests/services/test_shadow_actions.py
# Module 6 — experimentation / attribution / live-adaptation console
pytest tests/services/test_experiments.py tests/services/test_experiment_eval.py \
       tests/services/test_experiment_console.py tests/services/test_attribution.py
# Module 7 — governance gates
pytest tests/services/test_adaptive_action_gate.py tests/services/test_contact_governance.py \
       tests/services/test_campaign_governance.py
# operator endpoints (market refresh/state + experiment console + replay) — full app
pytest tests/integration/test_fulfillment_api.py
# the ratchets (agnostic core + observable failures)
pytest tests/test_no_flavour_in_core.py tests/test_no_silent_except_in_core.py
```

**Files that ARE the subsystem** (point GPT-5.5 here): `market_signal*.py`, `market_analysis.py`, `market_pipeline.py`, `market_replay.py`, `competitor_source.py`, `support_objection_source.py`, `funnel_source.py`, `shadow_actions.py`, `ranking_nudge.py`, `experiments.py`, `experiment_eval.py`, `experiment_console.py`, `attribution.py`, `adaptive_action_gate.py`, `contact_governance.py`, `campaign_governance.py` — all under `src/app/services/`.

---

## D. Browser clickthrough — operator Market Intelligence (the demo)

**Bring-up:** `./scripts/start_live_procurement_demo.ps1` (sets flags + seeds suppliers/catalog/competitor/objection/funnel demos), then on the operator tab (`:3001`) set `localStorage.setItem('ss_owner_key', '<OWNER_API_KEY>')`. Flags that matter: `FULFILLMENT_DEMO_ENABLED=1` (replay), `MARKET_PIPELINE_ENABLED=1` (live refresh), `COMMERCE_CATALOG_ENABLED=1` (competitor undercut needs price_book), `RANKING_NUDGE_EXPERIMENT_ENABLED=1` (the nudge actually fires).

**Operator → Market Intelligence tab** (`src/frontend/admin-react/src/components/MarketIntelligence.tsx`):

| Step | Click (data-testid) | Assert |
|---|---|---|
| 1 | **Reset** (`mi-reset`) | label `mi-label` = `SYNTHETIC REPLAY`, `mi-signals` = 0, `mi-findings-count` = 0 |
| 2 | day = **5** (`mi-day`) → **Advance** (`mi-advance`) | calm baseline remains visible: no active findings and **NOT** `demand_shift` yet |
| 3 | day = **7** → **Advance** | `mi-findings` now includes **demand_shift · conversion_anomaly · inventory_demand_mismatch · competitor_undercut · objection_cluster** — this is the **delta progression** (findings *change* as days advance) |
| 4 | **Refresh live data** (`mi-refresh-live`) | label flips to **`LIVE`**; `mi-findings` shows the REAL (default-tenant) findings from seeded competitor/objection/funnel data (deterministic) |
| 5 | **Ranking experiment** panel (`mi-experiment`): **Promote → live** (`exp-promote`) | `exp-status` badge = **LIVE** |
| 6 | **Evaluate now** (`exp-evaluate`) | a decision is recorded (uplift→decide→**auto-revert** on no-lift) |
| 7 | **Revert (kill)** (`exp-revert`) | `exp-status` ≠ LIVE — the kill lever stops adaptation globally |

**Backend it exercises:** `POST /api/v1/fulfillment/replay/{reset,advance?day=N}` + `GET /replay/state` (synthetic); `POST /fulfillment/market/refresh` + `GET /market/state` (real pipeline); `GET/POST /fulfillment/market/experiment/{state,promote,evaluate,revert}` (live-adaptation console). All operator-role.

---

## E. How to test **delta progression** (the deck's "sense → change → measure")

Delta progression = *the findings change as the world changes*, and the system measures whether its response helped. Two layers:

1. **Signal → finding delta (synthetic, deterministic):** the replay's 7-day curve. Advancing day-by-day, assert the finding SET grows: days 1–5 calm → day 6 competitor/objection appear → day 7 demand_shift + conversion_anomaly + inventory_demand_mismatch. The automated proof is `tests/services/test_market_replay.py::test_advancing_days_changes_findings` and `::test_heat_day_surfaces_competitor_and_objection_findings`. Manually: step `mi-day` 1→7 and watch `mi-findings-count` climb.
2. **Adaptation → uplift delta (the closed loop):** promote the experiment → treatment users get the nudge → record assignments + conversions → **Evaluate** computes control-vs-treatment uplift → decide keep/scale/revise/**revert**. Automated: `test_experiment_console.py::test_evaluate_auto_reverts_on_no_lift` + `test_experiment_eval.py`. The delta is the uplift %; a *negative* delta auto-reverts (the anti-"confidently make it worse" guard from deck Module 6).

**The cleanest single delta demo:** Reset → Advance to 5 (no demand_shift) → Advance to 7 (demand_shift appears) → Refresh live (LIVE findings) → Promote → Evaluate (uplift decision) → Revert. That's sense → interpret → decide → measure → govern in six clicks.

---

## F. GPT-5.5 browser clickthrough script (assertions)

1. Operator `:3001`, set `ss_owner_key`, open **Market Intelligence**.
2. `mi-reset` → assert `SYNTHETIC REPLAY`, 0 signals.
3. `mi-day`=5, `mi-advance` → assert calm baseline/no active findings, **no** `demand_shift`.
4. `mi-day`=7, `mi-advance` → assert findings include `demand_shift`, `competitor_undercut`, `objection_cluster` (screenshot — the delta).
5. `mi-refresh-live` → assert label `LIVE` (screenshot — real vs synthetic).
6. `exp-promote` → assert `exp-status` LIVE; `exp-evaluate` → assert a decision shows; `exp-revert` → assert not-LIVE.
7. (procurement cross-check) **Procurement** tab → run the buyer→supplier journey (see the live-demo runbook) to show the auditable-procurement track is intact.

**Buyer test prompt** (`:5173`, exercises the recommend path + procurement trigger): `"I need 20 gaming laptops for an esports lab, $1800 each within two weeks"` → assert recommendations + the procurement panel (GATE-1 commit). Current seeded stock has the top gaming SKU at 14 units, so quantity 20 creates a real 6-unit shortfall; quantity 10 is truthfully in stock. For market-intel specifically, the buyer side is indirect (signals are ingested from search/orders); the **operator** tab is where the market-intel demo lives.

**What to surface / fix if a click fails:** 401 → set `ss_owner_key`; empty live findings → `MARKET_PIPELINE_ENABLED` + run `seed_suppliers.py` (seeds competitor/objection/funnel) + `COMMERCE_CATALOG_ENABLED` (competitor undercut needs price_book); experiment never LIVE → `RANKING_NUDGE_EXPERIMENT_ENABLED`; replay disabled → `FULFILLMENT_DEMO_ENABLED`.

---

## G. What else to do (beyond the deck gaps)
- **Honest framing for the recording:** demo as *"Phases 1–3 live: sense (8 detectors over 7 real + synthetic sources) → advise (log-only proposals) → low-risk adapt (gated, reversible ranking nudge with auto-revert)."* Do **not** claim Phase 4–5 (offers/bundles/segments/channels execution) yet.
- **Next build (deck-ordered):** segments (M2/M4) → offer/bundle decisioning + execution (M4/M5, Phase 4) → channel performance. Each as its own flag-gated, parity-tested unit, like the sources.
- The `recommend.py` extraction (separate deep-dive doc) de-risks Module 5's storefront execution by giving the ranking stage clean boundaries.
