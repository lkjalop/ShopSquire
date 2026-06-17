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
| `test_recommend.py::test_broad_inferred_use_case_still_gets_domain_nqe_refinement` (×3 params) | fails alone **and** in-suite | A **real bug** (the `detected_use_case` resolution path returns `None` live), not a determinism issue. Scheduled for P3. Must stay red in both modes — any fixture that greens it in-suite is masking. |

## Rule going forward

- New tests must run consistently alone and in-suite (`determinism_check.py` in CI).
- Tests that hit `/api/v1/recommend/*` and seed catalog **must** use the
  `_make_isolated_engine` / `_override_app_engine` pattern so the request reads exactly
  their rows, not leaked session-engine rows.
- Never add a global state-clearing autouse fixture to "fix" flakiness — it masks.
