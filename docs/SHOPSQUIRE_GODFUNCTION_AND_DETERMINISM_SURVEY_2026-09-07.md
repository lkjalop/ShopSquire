# ShopSquire — The missing turn-boundary module, and a repo-wide determinism survey

**Date:** 2026-09-07 · **HEAD:** `50752a8b`
**Answers two questions:** (1) what happened to the module I said was missing after `recommend.py`
was archived, and (2) which other large files are deterministic-rule dumps.
All numbers below are AST-measured on the current tree.

---

# Part 1 — The module is not missing. It is the wrong shape.

## 1.1 The measurement

`src/app/routers/chat.py` is 5,823 lines and has 36 top-level definitions. One of them is
everything:

```
  4641 lines   L1107-5747   async _chat_query_impl      ← 80% of the file
   166 lines   L 491- 656   _cart_mutation_short_circuit
   126 lines   L 751- 876   _assess_image_compromise_breach
    79 lines   L1012-1090   async chat_query
```

Inside `_chat_query_impl`:

| Metric | Value |
|---|---|
| Lines | **4,641** |
| `if` statements | **283** |
| `try` blocks | **69** |
| Assignments | **712** |
| Calls | **2,101** |
| Max nesting depth | **9** |
| **Distinct local names assigned** | **446** |
| **Function-scoped imports** | **81** |
| Top-level statements | 271 (26 of them ≥ 40 lines) |

For comparison, the thing that was archived: `recommend.py::suggest()` spanned L4341–11591,
about **7,250 lines**. So the V2 retirement did not eliminate the god-function — it **halved
it and moved it** from the recommendation service into the chat router.

## 1.2 Why it keeps growing (the mechanism, not the symptom)

**446 local variables in one scope.** Every new governance requirement needs `products`,
`semantic_resolution`, `ambiguity_exploration`, `catalog_authority`, `server_research_result`,
`buyer_requirement_claims` and `_terminal_catalog` simultaneously in scope. The only place all
of those exist together is inside this function, so that is where the next feature lands.
That is why `chat.py` was the one file to grow in every delta of this arc.

**81 function-scoped imports.** Imports inside a function body are almost always a
circular-dependency workaround. Eighty-one of them says the module boundary is in the wrong
place — the router imports services that import back toward the router's concerns.

## 1.3 The seams, measured

The AST outline gives natural, already-contiguous phases. These are not a redesign; they are
the spans that already exist:

| Phase | Span | ~Lines | Largest statements inside |
|---|---|---|---|
| **Intake & preflight** | L1107–2100 | ~1,000 | image lockdown (92), case binding (75), source-URL intake (141) |
| Retrieval & turn shaping | L2100–3700 | ~1,600 | a **450-line** `try` (L2239), a 109-line `try`, a 104-line `try` |
| **Research entry** | L3700–4610 | ~900 | `provisional_exploration_needed` (**291**), research call + reconciliation (**199**) |
| **Response assembly** | L4762–4987 | ~230 | `out = {…}` (**226**) |
| **Terminal commit & projection** | L5081–5700 | ~620 | a **420-line** `try` (L5144), `terminal_outcome` (55) |

Three single statements account for 1,161 lines: the 450-line `try`, the 420-line `try`, and
the 291-line `if`.

## 1.4 Why this is now a *cheap* fix

The extraction pattern is already proven in this codebase, three times in the last delta:
`case_patch_grounding.py` (259 ln), `turn_outcome.py` (300 ln), `observability/stage_timer.py`
and `timescale_admin.py`. Those took `turn_router.py` from 3,249 → **2,801** and cleared three
of six size ceilings — **without raising a single limit**.

The same treatment applied to the two largest self-contained spans — **terminal projection**
(~620 lines) and **research entry** (~900 lines) — removes ~1,500 lines from
`_chat_query_impl`, brings `chat.py` under its 5,049 ceiling in one step, and gives the turn
boundary the module it has never had. Both spans have a clean interface: state in, typed
result out, no request object needed.

---

# Part 2 — Determinism survey of every file ≥ 400 lines

**Method.** For all 180 files ≥400 lines in `src/app` (161,849 lines total), I computed
`det/kloc = (re.* calls × 3 + hardcoded string-vocabulary terms + if-count) ÷ kloc`. High
density means the file *decides* things with hand-written rules rather than delegating to a
clamped model or a typed grammar.

## 2.1 Results

| lines | ifs | re() | terms | det/kloc | file | verdict |
|---:|---:|---:|---:|---:|---|---|
| 2,297 | 319 | 34 | **457** | **382** | `services/recommendations.py` | 🔴 **the one to kill** |
| 1,282 | 151 | 28 | 97 | 259 | `security/linked_artifact_analysis.py` | ✅ signatures — correct |
| 1,832 | 147 | 3 | 137 | 160 | `routers/vision.py` | 🟡 watch |
| 1,379 | 151 | 0 | 85 | 171 | `security/framework_correlation.py` | ✅ correct |
| 2,801 | 245 | 0 | 126 | 132 | `recommendation_core/turn_router.py` | 🟡 by design (the clamp) |
| 2,856 | 193 | 2 | 171 | 130 | `security/email_security.py` | ✅ correct |
| 2,461 | 157 | 1 | 161 | 130 | `main.py` | ✅ startup config |
| 4,025 | 378 | 15 | 90 | 127 | `routers/support_complaints.py` | 🟡 watch |
| 1,526 | 116 | 0 | 72 | 123 | `routers/cv.py` | ✅ correct |
| 1,465 | 121 | 0 | 59 | 123 | `services/recommendation_facade.py` | 🟡 watch |
| 1,616 | 116 | 0 | 76 | 119 | `services/official_workload_research.py` | 🟡 watch |
| 4,106 | 293 | 5 | 172 | 117 | `routers/admin.py` | 🟡 size, not rules |
| 3,929 | 339 | 0 | 78 | 106 | `services/orchestrator.py` | 🔴 **unreachable legacy** |
| 2,784 | 228 | 7 | 47 | 106 | `recommendation_core/core.py` | ✅ under ceiling |
| 5,823 | 367 | 22 | 147 | 100 | `routers/chat.py` | 🔴 see Part 1 |
| 3,203 | 11 | 0 | 14 | **8** | `routers/merchant_dashboard.py` | ✅ big but rule-free |

`merchant_dashboard.py` is the control case: 3,203 lines with a det/kloc of **8**. It is large
because it has many endpoints, not many rules. Size alone is not the problem — rule density is.

## 2.2 🔴 `services/recommendations.py` — the real patch-treadmill

**382 det/kloc, nearly 3× the next non-security file.** The worst offenders inside it:

| score | lines | ifs | re | terms | function |
|---:|---:|---:|---:|---:|---|
| 224 | 202 | 0 | 0 | **224** | `__init__` — a 202-line constructor that builds 224 hardcoded terms |
| 86 | 95 | 32 | 2 | 48 | `_infer_intents` |
| 72 | 149 | 39 | 2 | 27 | `_use_case_score` |
| 47 | 353 | 39 | 0 | 8 | `rerank_candidates_with_factors` |
| 47 | 164 | 32 | 1 | 12 | `analyze_query` |
| 40 | 81 | 13 | **8** | 3 | `_extract_price_range` |

Its classifier surface — `classify_budget_tier`, `_infer_use_case_tags`, `_use_case_score`,
`_infer_intents`, `_detect_buyer_type`, `_detect_compliance_request`, `parse_constraints` — is
a complete second recommendation brain, built entirely from keyword lists and `if` chains.
This is the V1 engine that survived the `recommend.py` archive.

**Reachability (the important part):**

- **Not** on the V2 chat path. `chat.py` never imports it.
- Eight non-test callers: `orchestrator.py`, `pricing.py`, `recommendation_explain.py`,
  `recommendation_nqe.py`, `flows/nqe.py`, `eval/runner.py`, `synthetic_reco_lab.py`,
  `use_case_advisor.py`.
- Reachable from the buyer UI through **one** door: `App.tsx:1524` →
  `/api/v1/recommend/why_product` → `recommendation_explain.explain_why_product`.

**And that door is guarded properly.** `explain_why_product` tries the canonical V2 fit
explanation first (from the trace, then from structured memory) and only falls through to
`RecommendationService.retrieve_candidates` + `rerank_candidates_with_factors` when both are
absent — an expired trace, an old session, or a SKU picked outside a V2 turn. The fallback
result is labelled `_explanation_scope: "catalog_only"`, so it is not a silent substitution.

That makes `recommendations.py` **the best archive candidate after `recommend.py`**: 2,297
lines and 457 hardcoded terms serving one labelled fallback path, plus eval/lab tooling.

## 2.3 🔴 `services/orchestrator.py` — 3,929 lines, unreachable from the buyer

339 `if`s, zero regex. **Not reachable from `chat.py`.** Its only callers are
`orchestrator_api.py` and `pricing.py` (plus one `_run_async_safe` helper import from
`recommend_pipeline.py`). This is a parallel legacy spine that no longer serves the buyer
journey. It needs a decision — archive, or state what it is still for.

## 2.4 Duplicate decision surfaces — better than the doctrine feared, with one real leak

The project's own doctrine says *"never add a second copy of a decision surface"*, and the
memory records the negated-over bug living in **four** budget parsers.

**Good news, measured.** I found 7 budget/price call sites, and they now **agree** on all
7 test phrasings, because they delegate:

- `answer_quality._extract_query_budget_bounds` — a pure facade over `parse_budget`.
- `answer_quality._extract_budget_threshold` — delegates, with a distinct floor-only purpose
  and its own `_NEGATED_OVER_RE` guard.
- `chat.py:321 _extract_budget_bounds` — *"Delegates FIRST to the canonical budget_grammar"*.

**The leak.** `chat.py:_extract_budget_bounds` keeps ~40 lines of **legacy fallback regex**
below the delegation, which runs whenever the canonical grammar declines. It can therefore
**override a deliberate refusal**:

| Query | `budget_grammar.parse_budget` | `chat._extract_budget_bounds` |
|---|---|---|
| `1500 to 2000 employees` | **None** (correctly not money) | **1500 – 2000** ← invents a budget |
| `I need 1500 laptops` | None | None ✅ |
| `15 laptops for 300 people` | None | None ✅ |
| `budget about 1900` | 1520–2280 | 1520–2280 ✅ |

One divergence in fourteen probes — small blast radius, but it is exactly the failure mode the
doctrine exists to prevent, and the fix is to delete the fallback.

**Still genuinely duplicated: use-case classification**, with five independent implementations —
`category_router._use_case_patterns_for`, `query_decomposer._use_case_patterns_for`,
`recommendations._infer_use_case_tags` + `_use_case_score`,
`recommend_budget_advisor._use_case_budget_floors`, `recommend_ranking._use_case_rank_details`.

---

# Part 3 — Recommended order

| # | Action | Size | Why now |
|---|---|---|---|
| 1 | **Delete the legacy budget fallback** in `chat.py:321` | ~40 lines | The only measured divergence from canonical truth; a pure deletion |
| 2 | **Extract terminal projection** from `_chat_query_impl` (L5081–5700) | ~620 lines | Largest self-contained span; typed state in, projection out; no request object needed |
| 3 | **Extract research entry** (L3700–4610) | ~900 lines | Second largest; 2 + 3 together put `chat.py` under its ceiling in one step |
| 4 | **Archive `recommendations.py`** behind the V2 explainer, or freeze it as the labelled fallback only | 2,297 lines / 457 terms | The real patch-treadmill; one guarded door left |
| 5 | **Decide `orchestrator.py`'s fate** | 3,929 lines | Unreachable from the buyer path |
| 6 | **Consolidate use-case classification** onto one surface | 5 implementations | The remaining true duplicate |

Items 2 and 3 are the ones that matter most: they give the turn boundary the module it has
never had, and they stop the file that has grown in every single delta of this arc.

---

## Method

AST analysis over `src/app` (180 files ≥ 400 lines, 161,849 lines); per-function density
scoring inside `recommendations.py` and `chat.py`; import-graph reachability checks for
`recommendations.py` and `orchestrator.py`; and a differential execution of the budget parsers
across 14 probe strings. No live model run was required for any of it.
