# Test Determinism (P0)

The suite is **order-dependent**: a few tests pass alone but fail in-suite (or vice
versa) because of shared mutable state. P0's goal is not "every test deterministic
tomorrow" — it is **a trustworthy verification signal**: isolated runs are reliable,
order-dependence is *measured* (never hidden), and no fixture is allowed to *mask* a
real failure.

## The harness

```
python scripts/determinism_check.py tests/test_recommend.py::test_a [more...]
```

Runs each target (a) **alone** in its own pytest process and (b) **in-suite** as part
of its file, then reports any test whose verdict differs. Exit code 1 on divergence —
wire it into CI as a gate. **Anti-masking contract:** a real bug must fail in *both*
modes; a test that passes in-suite but fails alone is flagged as masking, not "green".

## The P0 exit bar (what "thorough enough" means)

P0 is satisfied when **all** of these hold — not "full in-suite green":

1. The harness exists and can gate CI. ✅ (`scripts/determinism_check.py`, commit `e23cab8`)
2. The tests used to verify later work are reliable **in isolation**. ✅ (harness confirms `alone` runs are stable)
3. **No masking fixture in the tree.** ✅ (three global-fixture variants were prototyped and reverted — each masked the NQE bug)
4. Known order-dependent tests are documented with root cause (below).

Full in-suite determinism is explicitly **deferred**: it requires per-source bisection
against an engine-alignment / global-state rabbit hole, and the harness already makes
later phases verifiable without it.

## Why a global isolation fixture was rejected

Clearing shared state globally (DB rows, `DummyRedis`, `catalog_profile` + `lru_cache`s)
**masked the real NQE bug** — it flipped a test that legitimately fails alone into a
false green in-suite. Per the David/Opus handoff ("do not mask failures"), no such
fixture ships. Isolation must be **scoped per-test** (e.g. the `_make_isolated_engine`
/ `_override_app_engine` pattern), never a blunt global truncate.

## Known order-dependent tests (tracked, not hidden)

| Test | Behaviour | Root cause (investigated) |
|---|---|---|
| `test_recommend.py::test_image_hint_asus_uses_specific_brand_fallback_before_generic_windows` | passes alone, fails in-suite | **Not** DB rows / Redis / caches / engine — five isolation variants (3 global fixtures, a per-test catalog clear, and the isolated-engine pattern) all failed to fix it. Residual source is a non-DB global (env var, module/class global, or a monkeypatch leak in the image-brand path). Tracked; fix deferred. |
| `test_broad_inferred_use_case_still_gets_domain_nqe_refinement[high_school]` | flaky (order-dependent) | **WORKS in isolation** (faithful TestClient probe: `match→high_school`, `detected_use_case→NQE=high_school`, `ask_high_school_activity` IS generated). Its failures are order-dependence, not logic. |
| `…_nqe_refinement[university]` | flaky (order-dependent) | **WORKS in isolation** (probe: `detected_use_case=university_general`, `ask_university_subject` generated). Order-dependence, not logic. |
| `…_nqe_refinement[corporate]` | fails (real bug) | **Localized: NQE engine is CORRECT; the bug is in recommend.py post-NQE processing.** Decisive probe — `NextQuestionEngine.propose()` for the corp input returns `['ask_corporate_work_type', 'ask_budget_tier', 'ask_use_case']` (the domain question IS generated, for both `detected_use_case=office_general` and `None`). But the full `/suggest` request returns only `['ask_use_case']`. So `ask_corporate_work_type` is dropped by a recommend.py step AFTER `propose()` and AFTER `_filter_nqe_questions_by_missing_fields` (the filter *allows* it when `use_case` ∈ missing_fields). Next: trace the `next_questions` reassignments between the NQE call (`recommend.py:~10135`) and the response for the `office_general` path. Deferred to focused recommend.py work — do NOT hasty-fix (hs/uni currently work in isolation; a careless change to the shared path breaks them). |

## Pre-existing failures (fail even in isolation — NOT order-dependence, NOT regressions)

These fail when run **alone**, so they are genuine pre-existing logic gaps in recommend.py,
not flakiness and not caused by the strangler-fig extraction. Verified by stashing the
checkout-handoff extraction (commit `292a2b4`) and re-running at baseline: **identical**
failures. Listed here so future stage-extraction work does not mistake them for new breakage.

| Test | Assertion that fails (baseline + HEAD, identical) |
|---|---|
| `test_recommend.py::test_followup_reference_without_shortlist_prompts_disambiguation` | `body.get("needs_disambiguation") is True` → `False` (returns `ambiguity_reason: missing_budget` but not the disambiguation flag) |
| `test_recommend.py::test_nqe_post_results_uses_image_product_type_category` | `assert []` — empty `results` for the image-product-type path |

Protocol for the next extraction: if a test fails after your change, run it **alone** and
also at baseline (`git stash -u` the change). A failure present in *both* is pre-existing;
only a failure your change *introduces* (passes at baseline, fails at HEAD) is a regression.

## Rule going forward

- New tests must run consistently alone and in-suite (`determinism_check.py` in CI).
- Tests that hit `/api/v1/recommend/*` and seed catalog **must** use the
  `_make_isolated_engine` / `_override_app_engine` pattern so the request reads exactly
  their rows, not leaked session-engine rows.
- Never add a global state-clearing autouse fixture to "fix" flakiness — it masks.
