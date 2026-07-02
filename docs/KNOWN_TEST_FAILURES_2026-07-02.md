# Known pre-existing test failures (bare local `pytest`) — 2026-07-02

**Purpose:** de-noise the audit. These fail in a **bare local `python -m pytest`** run (fresh sqlite,
no Ollama/Redis, current clock). Every one was proven **pre-existing** — it also fails at commit
`e11f725` (before this session's work) and lives in code this session never touched. **None are
regressions. None are demo-breaking** (the live backend replay returns 6 findings; see below).

They are **not marked `skipif`** on purpose: two of them (the order-flakes) reveal a real cross-test
pollution issue, and the market ones are clock-relative — hiding them would mask genuine debt. This
doc is the honest record instead.

## What WAS fixed this session
- **Demo-`.env` flag bleed → FIXED** (`tests/conftest.py`, commit `d6c7fc9`). `FULFILLMENT_DEMO_ENABLED`
  / `FULFILLMENT_AUTO_DRAFT_ON_COMMIT` from the demo `.env` were bleeding into the test process and
  breaking three "default-off" tests. Now forced off in `pytest_sessionstart`; 300-test collateral green.

## Remaining (7) — root cause, category, proof

| Test | Category | Root cause (verified) |
|---|---|---|
| `test_recommend.py::test_price_filter_nearest_viable_band_can_fall_back_below_requested_window` | **Order-flake** | Passes in isolation; fails only in a big mixed batch → cross-test state pollution (shared catalog/Redis/event-log). |
| `test_recommend.py::test_negation_excludes_brand_end_to_end` | **Order-flake** | Same — passes isolated, fails in batch. |
| `test_recommend.py::test_selection_explanation_requests_llm_summary_and_trace` | **Narration routing / state** | The "why selected" explain path only calls `_summarize_results` when `assistant_message is None and llm_summary_requested` (`recommend.py:10632`). For a fresh uid with **no prior shortlist**, `llm_summary_requested` isn't set → the stubbed summarizer is never reached (`calls==0`). Needs realistic prior-session state; `USE_LLM_SUMMARY=1` is necessary but not sufficient. |
| `test_security_observer_paths.py::test_observer_logs_for_recommend` | **Env (observer/Redis)** | No `security_events` row written for `/recommend/suggest` in the bare env — the observer sync path isn't producing the payload event without the real observer/Redis backing. |
| `test_market_pipeline.py::test_pipeline_ingests_real_rows_and_persists_findings` | **Clock/time-rot + ingestion** | Fixture seeds `search_events` dated **2026-06-20..24**; `run_pipeline` ingests the order but **0 search_events** (`ingested_by_source.search_events == 0`) → 0 findings. Clock-relative (today is 2026-07-02). |
| `test_market_pipeline.py::test_pipeline_is_idempotent_on_reingest` | **Clock/time-rot** | Same fixture as above. |
| `test_market_replay.py::test_load_run_produces_findings` | **Clock/time-rot (service data)** | `market_replay._DATES` is hardcoded `2026-06-20..26`; in a bare fresh-DB run the analysis yields **0 persisted**. Confirmed time-rot: forcing `_DATES` to recent → 6 findings incl. `demand_shift`. **NOTE:** the *live* running backend still returns 6 findings (accumulated demo data), so the demo is not broken — but this data layer (also `competitor_source`, `funnel_source`, `support_objection_source`, all pinned to `2026-06-26`) will rot and deserves a deliberate "relative-date" fix. |

## Recommended fixes (deliberate, not done here)
1. **Market time-rot (3 tests + demo hygiene):** make the synthetic demo dates relative to "now" across
   `market_replay._DATES`, `competitor_source`, `funnel_source`, `support_objection_source`, and the
   `test_market_pipeline` fixture. One coordinated change; needs demo re-verification. *Do not blind-fix —
   the live demo currently works and a bad rewrite could break it.*
2. **Order-flakes (2 tests):** hunt the leaking test (catalog/Redis/event-log state) and add the missing
   reset — same class as the ASUS/`grounding_ladder` cache fix already in `conftest.py`.
3. **Narration explain test (1):** seed a prior shortlist in the test, or adjust the explain path to set
   `llm_summary_requested` on an explicit "why selected" query without prior state.
4. **Observer test (1):** run under the real observer/Redis env, or stub the observer sink.

## For the GPT-5.5 audit
Run the unit suite and treat the 7 above as **known pre-existing** (this file). Regression signal =
*new* failures beyond this list. The ratchets (`test_no_flavour_in_core`, `test_no_silent_except_in_core`,
`test_no_untimed_outbound_http`) and the touched-area suites (chat, recommend-unit, fulfillment, planner)
are green.
