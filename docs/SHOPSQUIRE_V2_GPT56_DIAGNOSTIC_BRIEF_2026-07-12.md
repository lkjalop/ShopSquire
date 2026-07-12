# GPT-5.6 — Diagnostic Test Brief (2026-07-12, HEAD 546f53c)

Review-7's live reading (empty 16.67%, **constraint-sat 39.44%**) says the V2 search core is
quality-red before labels. This brief is the exact investigation to run next. **Goal: decide
whether 39.4% is a DATA gap (products lack specs), a RANKING/RETRIEVAL gap (unsuitable products
shown/retrieved), or a METRIC mis-population — and confirm the P0 fixes hold live.** Do NOT lower
thresholds.

## Test 1 (PRIMARY) — decompose the constraint-satisfaction failure
```powershell
python tests/characterization/shadow_replay.py --facade-mode --diagnose
```
New `--diagnose` mode writes `tmp/quality_diagnosis.json` + prints the decomposition. **Report:**
- the `verdicts` split — **meets / unknown / fails** counts, and `constraint_sat`.
- `top_unknown_keys` vs `top_failed_keys`, and the one-line `READ`.
- **The decisive question:** is it **unknown-dominated** or **fails-dominated**?
  - *unknown-dominated* → the shown products have no value for that attribute in the catalog
    (e.g. `gpu_vram_gb` absent). Then this is a **catalog-onboarding / attribute-extraction**
    problem, not a core bug — verify by checking whether the demo `products.specs` actually
    contain ram/gpu/refresh, and whether `attribute_registry.variant_attributes` extracts them.
  - *fails-dominated* → products are present and genuinely below the requirement → a
    **retrieval/ranking** problem in the core (it's surfacing unsuitable units).
- For the top unknown key(s): pick 3 SKUs flagged unknown and report their raw `specs` from the
  DB — do they have the spec (extraction bug) or not (data gap)?

## Test 2 — the empty-rate (16.67%)
From `tmp/quality_diagnosis.json`, list the `empty:true` cases. **Report:** are they the WORKLOAD
cases (cyberpunk / valorant / AutoCAD) where the C1 reroute + the requirements-broad retry should
have surfaced device laptops? For each empty case, is the empty a **retrieval miss** (node routed
but `_skus_for_node` returned nothing / text fallback empty) or a **genuine no-match**? This tells
us if the reroute (M3-C1) is actually firing in the census.

## Test 3 — the two screenshots, live
Run these exact turns against the running stack (V2 core on for this probe:
`RECOMMEND_CORE_MODE=primary` in a THROWAWAY shell, or via the replay `--only`) and report the
products + their per-product fit verdicts:
- **"a laptop to play cyberpunk 2077, budget 2300"** — does V2 (a) route to a device node, (b)
  carry a `gpu_vram_gb` floor from the workload, (c) rank a discrete-GPU laptop above the zero-GPU
  IdeaPads, (d) mark the zero-GPU picks `fails` not `meets`? (The legacy screenshot showed
  score-100 zero-GPU top picks — does V2 fix or reproduce it?)
- **"laptop for valorant at 144fps"** — non-empty? reroute to gaming laptops? refresh_hz floor
  applied?
- NOTE: the multi-turn **budget-loss** (screenshot 30, follow-up dropping $2300) is NOT testable
  in the replay until P1.3 stateful lands — flag it, don't chase it here.

## Test 4 — confirm the P0 fixes hold live
- **Single-flight idempotency** (`dcc7d0e`): fire a chat turn whose stream is slow enough to hit
  the 3.5s connect timeout → the frontend fires the `/chat/query` fallback with the SAME
  `Idempotency-Key`. Confirm the resolver runs ONCE (one proposal / one trace), not twice. (Or
  unit-drive `_idem_single_flight` with a slow producer + a concurrent duplicate.)
- **Transactional cart CAS** (`2e9ce8b`): if a live/concurrent harness is feasible, confirm a
  stepper `PUT /cart/items` landing between a plan's propose and apply → the apply returns
  `stale_cart` and the stepper's edit survives (the versioned CAS). The unit test
  `test_stepper_between_propose_and_apply_wins_no_lost_write` covers the logic; a live confirm is
  the bonus.

## Test 5 (if time) — adversarial fit spot-check
Pick 3 corpus queries with explicit numeric requirements (e.g. "16GB RAM or more", "1TB",
"144fps"). Confirm the router extracts them as ranges (B1), the fit stage marks below-threshold
products `fails`, and NO over-budget/duplicate product is shown (the `unauthorized` metric = 0
should hold — verify it isn't hiding missing-price products now that missing price counts as a
violation).

## What to report back
1. The **unknown-vs-fails verdict** on the 39.4% (Test 1) — this decides the next fix.
2. Whether the reroute + broad-retry actually fire on the empty workload cases (Test 2).
3. The cyberpunk/valorant live behavior (Test 3) — fixed or reproduced.
4. Single-flight + CAS confirmed live (Test 4).
5. Anything the diagnosis surfaces that the metric MIS-reads (e.g. constraint-sat counting an
   EXPLAIN turn's non-product answer) — a metric bug is as important as a core bug.

## What NOT to do
No canary, no archiving `suggest()`, no threshold-lowering, no concluding "V2 is broken" before
the unknown-vs-fails read — a data/extraction gap is fixed very differently from a ranking bug.
