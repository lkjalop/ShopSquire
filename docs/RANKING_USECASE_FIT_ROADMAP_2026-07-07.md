# Use-case fit ranking — comprehensive fix + roadmap

**Date:** 2026-07-07 · **Trigger:** screenshot-27 ("8GB laptop recommended as *best fit* for LLM training").
**Verdict:** the message fix already ships; the remaining dumbness is a **ranking/framing** defect with a
single structural root cause. This is agnostic-core work — no product literals, KB + specs fields only.

---

## 1. Root cause (one sentence)

**Two different data sources judge "does this product fit the use case," and they can disagree:**

| Judgment | Source | File:line |
|---|---|---|
| Ranking "fit" → sets `factors.use_case_conflicts` → drives `summarize_use_case_fit.exact_fit` → the **"Best fits" vs "Closest options"** wording | profile **`ranking_conflict_rules`** via `_evaluate_conflict_rules` | recommend_ranking.py:164 (`_use_case_rank_details`), :180, :385, :442 |
| Challenge-defense "fit" → "meets / falls short on RAM" | **`use_case_kb.required_specs`** (`ram_gb_min:32`, `storage_gb_min:1000`, `gpu_vram_gb_min:8`) | recommend_justification.py:56 (`build_challenge_justification`) |

So a product (e.g. a 16GB-RAM laptop) can **pass** the ranking rules → get labelled **"Best fit for AI work"**
in the message, while the challenge-defense reading the KB says it **"falls short — RAM 16 vs 32."** That is
the exact contradiction in screenshot-27. The fix is to make the **KB `required_specs` the single fit
authority** that both the ranking and the message obey.

Note: with the current catalog the $3,499 Alienware (vram 8 / ram 32 / storage 1024) *does* meet every KB
floor and is in budget, so today's backend happens to rank it #1 — but nothing *enforces* that; a catalog
change or a use-case with no in-budget floor-meeter reproduces the dumbness immediately.

---

## 2. The comprehensive fix (4 parts, all agnostic-core)

### RK1 — KB-floor conflict tagger, wired into ranking  **(P0, the root cause)**
Make a product that fails a KB `<field>_min` floor carry a `use_case_conflict`, so `summarize_use_case_fit`
turns `exact_fit=False` when the whole in-budget set fails — which the message layer already honours.

- **New (agnostic):** `recommend_ranking.kb_requirement_conflicts(specs: dict, use_case_key: str) -> list[str]`
  — loads `use_case_kb`, walks `required_specs` keys ending `_min`, compares `specs[field]` (numeric) to the
  floor, returns labels like `"RAM 16GB < 32GB required"`. Reuses the same KB loader as
  `recommend_justification` (`load_capability_kb`) and the same fuzzy id-resolve (`ml_ai→ai_ml_workstation`).
- **Wire:** in `_use_case_rank_details` (recommend_ranking.py:164) merge `kb_requirement_conflicts(...)` into
  the returned `conflicts`, and subtract a score penalty per miss (mirror the −20/miss at :435). Now the
  16GB-RAM LOQ is tagged; the 32GB Alienware is not.
- **Files:** `src/app/services/recommend_ranking.py` (:164 add call, :385 already stores conflicts), reuse
  `src/app/services/recommend_budget_parsing.py::load_capability_kb`.
- **Effort:** ~1.5h · **Risk:** low (additive tags + score nudge; existing fit machinery consumes it).

### RK2 — "Best fits" must exclude floor-failing products  **(P0, framing)**
Mostly automatic once RK1 tags conflicts (`exact_fit=False` → advisor emits "Closest options with
trade-offs", advisor.py:960). Two guards to add:
- In `_deterministic_assistant_message` (recommend_budget_advisor.py:923) strengthen `_positively_fits_use_case`
  to ALSO reject rows carrying `factors.use_case_conflicts` (today it only checks for a positive
  `use_case_match` tag) — so a conflict-tagged row can never be picked as a "best fit."
- When `exact_fit=False`, NAME the gap in the message using the KB (reuse
  `recommend_justification.build_challenge_justification` or a trimmed variant): *"Closest in budget is the
  LOQ, though it's short on RAM (16GB vs 32GB) for sustained training."*
- **Files:** `src/app/services/recommend_budget_advisor.py` (:923, :957-969).
- **Effort:** ~1h · **Risk:** low.

### RK3 — Surface the cheapest FLOOR-MEETING option as a labelled card  **(P1, the "here's what clears the bar")**
Today `_above_budget_step_ups` (advisor) names step-ups in TEXT only. Extend to a structured card the
right-panel renders:
- New `recommend_ranking.cheapest_requirement_meeting_sku(use_case_key) -> row|None` — cheapest catalog row
  (any price) that meets EVERY KB floor. If it's over budget, mark `over_budget=True`.
- Add it to the payload's right-panel contract as an "Also meets every requirement" card (over-budget clearly
  badged), so the buyer can choose to stretch instead of only reading about it.
- **Files:** `src/app/services/recommend_ranking.py` (new fn), `src/app/routers/recommend.py` (right-panel
  assembly ~11076 `_assemble_right_panel`), `frontend/src/components/*` (render the badged card).
- **Effort:** ~half day (touches the panel contract + a frontend card) · **Risk:** medium (UI surface).

### RK4 — Unify the two fit sources (single source of truth)  **(P2, architectural cleanup)**
The durable fix: profile `ranking_conflict_rules` and `use_case_kb.required_specs` should not be two
independent truths. Make `ranking_conflict_rules` DERIVE from the KB `required_specs` (or delete it in favour
of the KB), so "fit" is defined once. Guard with a test asserting the ranking's fit verdict and the
challenge-defense's verdict agree for every KB use-case.
- **Files:** `src/app/services/recommend_ranking.py::_ranking_conflict_rules_for`, `config/store_profiles/*`,
  `config/use_case_kb.json`, new parity test.
- **Effort:** ~half day · **Risk:** medium (changes ranking inputs; needs the battery).

---

## 3. Relevant files (assessment)

| File | Role | What changes |
|---|---|---|
| `src/app/services/recommend_ranking.py` | fit scorer + conflict tagger + fit summary | RK1 add `kb_requirement_conflicts` + wire at :164; RK3 add `cheapest_requirement_meeting_sku`; RK4 unify `_ranking_conflict_rules_for` |
| `src/app/services/recommend_budget_advisor.py` | message builder ("Best fits" / "Closest options") | RK2 strengthen `_positively_fits_use_case` (:923), name the gap when `exact_fit=False` (:957-969) |
| `src/app/services/recommend_justification.py` | KB spec-vs-requirement engine (challenge-defense) | reused by RK1/RK2 as the shared fit authority; no change |
| `src/app/services/recommend_budget_parsing.py` | `load_capability_kb` (the KB loader, path fixed in N4) | reused by RK1 |
| `config/use_case_kb.json` | `required_specs` floors — the fit authority | RK4 becomes the single source |
| `src/app/routers/recommend.py` | `summarize_use_case_fit` call (:10245), right-panel (:11076) | RK3 right-panel card |
| `frontend/src/components/*` | product panel | RK3 render the "meets every requirement (over budget)" card |

---

## 4. Roadmap & sequencing

1. **RK1 + RK2 together (P0, ~2.5h, low risk)** — this alone kills the visible dumbness: fit is judged by the
   KB, "Best fits" can never name a floor-failing product, and when nothing in budget clears the bar the
   message says so honestly. **Do before the recording.**
2. **RK3 (P1, ~half day)** — the over-budget floor-meeter as a card. High demo value ("here's what actually
   clears the bar"), but touches the panel + a frontend card — do right after RK1/RK2 land + a re-record.
3. **RK4 (P2, ~half day)** — collapse the two fit sources to one. The durable correctness win; post-demo.
4. **Option C (separate track, the other doc)** — in-process `suggest_core` + full-context pass for latency +
   silent-context-loss. Orthogonal to ranking; post-demo, own PR.

---

## 5. Immediate ops (not code)
- **Restart `npm run dev` on :5173.** Screenshot-27's stale challenge ("No exact in-catalog match") and the
  $1,199-as-best-fit panel are a **stale Vite bundle** — the current backend already ranks the clean-fit
  Alienware #1 and fires the full challenge-defense (both reproduced live). Hard-refresh alone won't help if
  the dev server didn't rebuild.

---

## 6. Why this is the honest fix
It makes ONE thing true everywhere: *"fits the use case" == meets the KB `required_specs`.* The ranking, the
"Best fits" wording, the challenge-defense, and (RK3) the surfaced alternative all read the same floors. The
platform stops recommending a product it will later admit "falls short" on — which is exactly what made
screenshot-27 read dumb.
