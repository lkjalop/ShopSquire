# recommend.py Core/Adapter Split — Authoritative Roadmap (2026-06-18)

Single source of truth for decomposing `src/app/routers/recommend.py`. Reconciles GPT-5.5's split
plan with completed work and **re-verified current line numbers** (GPT-5.5's were stale after the
image-hint extraction). Supersedes the loose line refs in that plan.

## Current state (verified, 2026-06-18 — after stage #2)

- `recommend.py` = **13,731 lines** (was 14,588 at session start).
- ~356 `except Exception` blocks (splitting each stage shrinks the silent-fail surface).

## Completed splits

| Stage | New module | Result |
|---|---|---|
| ✅ checkout-handoff leaf | `services/checkout_handoff.py` | first stage, RecommendContext seed (commit `292a2b4`) |
| ✅ image-hint stage | `services/recommend_image_hints.py` | `_safe_image_hints_for_fast_path` + brand patterns + constants; 14,680→14,588 |
| ✅ **foundation (PR-A)** | `services/recommend_utils.py` | shared **pure leaf utils** `_candidate_matches_brand`, `_brand_display_name`, `_result_price_dollars`, `_extract_candidate_numeric_specs` — used by BOTH ranking and stage builders. Breaks the circular-import knot so stage services never import the router (commits `8d901a4`, `5482470`) |
| ✅ **#2 Budget/Brand advisor** | `services/recommend_budget_advisor.py` | 9 pure builders moved (AST byte-identical): `_build_brand_budget_answer(+_v2)`, `_deterministic_assistant_message`, `_build_budget_reasoning_note`, `_budget_reasoning_requested`, `_assess_budget_fitness`, `_build_minimum_recommended_tiers`, `_persona_summary_label`, `_USE_CASE_BUDGET_FLOORS`. 14,438→13,731 (commit `de90d66`) |

## Foundation finding (the keystone — discovered while executing #2)

GPT-5.5 (and my own first pass) called the budget builders "pure ⇒ safest, low risk." True for
*purity*, but the naive lift is unsafe for two reasons found in execution:

1. **The shared-helper web is real.** The budget builders depend on `_candidate_matches_brand`,
   `_brand_display_name`, `_result_price_dollars`, `_extract_candidate_numeric_specs` — all of
   which are ALSO used elsewhere in `suggest()`/ranking. Moving the builders while those stay in
   the router would force the new service to import the router → **circular import**. Fix:
   `recommend_utils.py` first (PR-A/#2a), then the stage imports from there. **Every later stage
   needs this same shared module.**
2. **The duplicated nested helpers DIVERGE — never dedup them.** `_extract_budget_value` and
   `_generic_budget_floor` exist as nested copies in both `_build_brand_budget_answer` and `_v2`,
   but the copies differ (v2's `_extract_budget_value` handles ranges; its gaming floor is 900 vs
   1200). A "dedupe to one shared helper" would silently change behaviour. The AST source-span
   move keeps each copy with its owner → byte-identical, parity by construction.

**Method that worked:** mechanical AST source-span extraction (a throwaway script reads the exact
`lineno..end_lineno` of each target node, writes the new module verbatim, deletes the spans from
the router) → moved code is byte-for-byte identical, so behaviour is preserved *by construction*;
characterization tests + the full suite then confirm. Re-export-identity is asserted in each test
(`router.fn is service.fn`).

## The implementation rule (shared by every stage)

A typed stage state instead of threading 40 locals (GPT-5.5's `RecommendStageState`, my
`RecommendContext` expanded). Each pure stage is `stage(state) -> state | typed_result`,
characterization-parity tested, re-exported from recommend.py for back-compat:

```python
@dataclass
class RecommendStageState:
    query: str; uid: str; constraints: dict
    image_context: dict; image_cv_signals: dict
    results: list[dict]; timing_breakdown: dict
    source_statuses: list[dict]; trace_id: str | None; flags: dict
```

## Ordering principle (REVISED from GPT-5.5)

**Pure-first, DB-bound-last.** GPT-5.5 ordered fast-path (#2) before budget (#3), but the
fast-path is **DB-bound** (`_top_up_image_results`/`_fast_path_catalog_recommendation` call
`db.execute`) while the budget-answer builders are **pure** (verified: zero db/request refs in the
4937–6227 region). Pure stages extract with characterization parity alone; DB-bound stages need
the `RecommendStageState` threaded first or they just relocate coupling. So:

Line numbers below are **pre-#2** and now stale (the #2 move shifted everything after ~2500).
Re-verify with grep before each stage (the proven loop, step 1). Stages #3–#6 remain:

| # | Stage | New file | Targets (re-grep before starting) | Purity | Risk |
|---|---|---|---|---|---|
| ✅ **2** | ~~Budget/Brand advisor~~ **DONE** | `services/recommend_budget_advisor.py` | see Completed splits | pure | shipped |
| 3 | NQE stage | `services/recommend_nqe_stage.py` | `_resolve_nqe_product_category`, `_build_question_plan`, `_apply_nqe_selection_to_constraints`, main NQE block (in-suggest) | mostly pure (Redis for slot state) | med |
| 4 | Narration / Why | `services/recommend_narration_stage.py` | `_build_persona_prompt_context`, `_summarize_results` | pure builders + 1 LLM call | med (claim-grounding) |
| 5 | Fast catalog path | `services/recommend_fast_path.py` | `_fast_path_product_score`, `_fast_path_catalog_recommendation`, `_top_up_image_results`, `_parse_fast_path_image_inputs` | **DB-bound** | med — needs `RecommendStageState` |
| 6 | Non-suggest routes | `routers/recommend_feedback.py` (+ split) | `/checkout_upsell`, `/why_product`, `/interaction`, `/feedback`, `/cf/train`, `/nqe_slots`, `/nqe_feedback`, `/admin/nqe_feedback_summary` | route-local | low–med (each route drags ~15 router-level helpers/imports — NOT as mechanical as first assumed; audit before moving) |

### Why each stage (the rationale GPT-5.5 gave, kept)

- **Budget/Brand advisor** — turns "why this fits your budget/use-case" into defensible evidence,
  not copywriting. Pure ⇒ safest next step. Also where the remaining brand/spec FLAVOUR prose
  (rtx/144hz/gaming) lives → profile-back during the move (Phase 2 overlap).
- **NQE stage** — the bridge to smarter query decomposition; must be profile-driven *before* more
  LLM reasoning (ties to the `QueryUnderstanding` contract).
- **Narration/Why** — where unsupported claims leak; must consume structured evidence, not
  route-local state. The finalizer already guards claims (`recommend_response_finalizer`).
- **Fast catalog path** — the latency story; isolate + time + test. DB-bound, so do it *with* the
  state object.
- **Non-suggest routes** — shrinks the router with zero recommendation-behaviour change.

## Projected size after each split

```
session start: recommend.py 14,588
after PR-A:    14,527  (shared brand/price leaf utils out)
after #2a:     14,438  (shared spec parser out)
after #2:      13,731  ✅ ACTUAL (budget cluster out — bigger than the ~14,150 estimate: the
                        cluster was 707 net lines incl. _deterministic_assistant_message 147 +
                        _build_brand_budget_answer 225)
after #3:      ~13,200  (NQE)
after #4:      ~12,700  (narration)
after #5:      ~12,200  (fast-path, DB-bound)
after #6:      ~11,500  (non-suggest routes out of this file)
```

The **< 7k file** target is reached around #4–#5; the **< 2k suggest()** target needs the
RecommendStageState pipeline (each in-suggest stage block calls a service), which lands with #3–#5.

## Per-stage checklist (the proven loop)

1. Verify target purity (db/request/Redis refs) — pure ⇒ parity only; impure ⇒ thread state.
2. Move the cohesive cluster + its private helpers to the new service.
3. Re-export from recommend.py (shim) — internal call-sites + tests unchanged.
4. Characterization test the service; repoint stage-specific tests to the service module.
5. `git stash -u` the change, run the affected suite at baseline, diff failures — **only a
   failure your change introduces (passes at baseline, fails at HEAD) is a regression.** The 6
   documented `test_recommend.py` failures fail identically at baseline (see DETERMINISM.md).
6. Commit iteratively; never bundle two stages.

## How this fits the bigger picture

This split is **Phase 5** of the canonical roadmap (`SHOPSQUIRE_ROADMAP_CANONICAL_2026-06-18.md`).
It runs in parallel with Phase 2 flavour excision: each stage extracted is also a chance to push
its inline flavour (budget prose, NQE templates, persona vocab) to the StoreProfile — the modules
then join the no-flavour lint. Core (decide/rank/finalize/retrieve/gates) stays put; only the
stage *organisation* and the *flavour* move.
