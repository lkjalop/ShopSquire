# recommend.py Core/Adapter Split — Authoritative Roadmap (2026-06-18)

Single source of truth for decomposing `src/app/routers/recommend.py`. Reconciles GPT-5.5's split
plan with completed work and **re-verified current line numbers** (GPT-5.5's were stale after the
image-hint extraction). Supersedes the loose line refs in that plan.

## Current state (verified)

- `recommend.py` = **14,588 lines**.
- `suggest()` = lines **6227 → 13910** (≈ **7,683 lines**, 53% of the file).
- 8 non-suggest `@router` endpoints below suggest (13910–14588, ≈ 680 lines).
- ~356 `except Exception` blocks (splitting each stage shrinks the silent-fail surface).

## Completed splits

| Stage | New module | Result |
|---|---|---|
| ✅ checkout-handoff leaf | `services/checkout_handoff.py` | first stage, RecommendContext seed (commit `292a2b4`) |
| ✅ image-hint stage | `services/recommend_image_hints.py` | `_safe_image_hints_for_fast_path` + brand patterns + constants; 14,680→14,588 |

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

| # | Stage | New file | Verified targets (current lines) | Purity | Risk |
|---|---|---|---|---|---|
| **2** | **Budget/Brand advisor** | `services/recommend_budget_advisor.py` | `_build_brand_budget_answer` **4937**, `_build_brand_budget_answer_v2` **5164**, `_deterministic_assistant_message` **5862**, `_assess_budget_fitness` **2493**, `_build_minimum_recommended_tiers` **2541** (+ helpers `_extract_budget_value`, `_generic_budget_floor`) | **pure** | low |
| 3 | NQE stage | `services/recommend_nqe_stage.py` | `_resolve_nqe_product_category` **1440**, `_build_question_plan` **1650**, `_apply_nqe_selection_to_constraints` **3481**, main NQE block (in-suggest ~12400) | mostly pure (Redis for slot state) | med |
| 4 | Narration / Why | `services/recommend_narration_stage.py` | `_build_persona_prompt_context` **4188**, `_summarize_results` **4499** | pure builders + 1 LLM call | med (claim-grounding) |
| 5 | Fast catalog path | `services/recommend_fast_path.py` | `_fast_path_product_score` **741**, `_fast_path_catalog_recommendation` **837**, `_top_up_image_results` **628**, `_parse_fast_path_image_inputs` **784** | **DB-bound** | med — needs `RecommendStageState` |
| 6 | Non-suggest routes | `routers/recommend_feedback.py` (+ split) | `/checkout_upsell` **13910**, `/why_product` **14114**, `/interaction` **14193**, `/feedback` **14273**, `/cf/train` **14377**, `/nqe_slots` **14397**, `/nqe_feedback` **14458**, `/admin/nqe_feedback_summary` **14553** | route-local | low (mechanical) |

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
now:           recommend.py 14,588 | suggest() 7,683
after #2:      ~14,150 | suggest() ~7,400   (budget builders out)
after #3:      ~13,700 | suggest() ~7,000
after #4:      ~13,100 | suggest() ~6,500
after #5:      ~12,600 | suggest() ~6,100
after #6:      ~11,900 | non-suggest routes out of this file
+ big builders (_fast_path_catalog 493, _summarize_results 367) as services → < 11k, suggest() ~5k
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
