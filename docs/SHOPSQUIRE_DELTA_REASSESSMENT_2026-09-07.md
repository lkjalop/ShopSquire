# ShopSquire — Delta Re-assessment: what is done, what is left

**Date:** 2026-09-07 · **HEAD:** `50752a8b` (was `be3382b9` at my last assessment)
**Delta measured:** 8 commits · 99 files · **+6,482 / −950**
**Working tree:** 1 modified file, 0 untracked
**Supersedes:** `SHOPSQUIRE_EXTERNAL_SEARCH_ROUND6_ASSESSMENT_2026-09-04.md`,
`SHOPSQUIRE_PLATFORM_DEEPDIVE_AND_TEST_PLAN_2026-09-07.md`

Method: independent re-derivation. I re-ran every probe from my previous two assessments
against the current code rather than reading the repair receipts, then went looking for new
defects. Claims below are labelled by how they were obtained.

---

## 0. Verdict

**This is the largest genuine step forward in the arc.** Of the eleven items on my 09-04
next-step list, **eight are closed**, one is partially closed, and two remain open. Three
long-standing findings that predate this arc are also closed — including the 2026-08-24
Cairns intake-boundary defect and a live secret leak I had not previously found.

The two headline problems I identified are both fixed at the root, not papered over:

- **Product delivery.** The catalog universe is now derived server-side through a typed
  `CatalogScope`. Measured: `"is 3000 enough for pragmata?"` with **no client taxonomy
  handle** now returns **11 candidate configurations** — it returned **0** on 09-04.
- **Ambiguity convergence.** "Did you mean X?" is now answerable, by chip click or by
  free-text "yes"/"correct"/"no", and the confirmed identity rewrites the effective query.

What is left is smaller but not trivial: one **new** deterministic defect I found this pass
that explains the only failing live browser test, `chat.py` still growing, and a
test-infrastructure fault that writes to a tracked config file and poisons later tests.

---

## 1. Delta inventory

| | 09-04 (round #6) | Now |
|---|---|---|
| State | uncommitted, 44 modified / 12 untracked | **8 commits**, 1 modified / 0 untracked |
| Size | +2,060 / −209 (43 files) | **+6,482 / −950 (99 files)** |
| Architecture ratchet failures | 3 | **1** |
| Size-guard breaches | 6 | **3** |
| `except Exception` in `chat.py` | 80 (baseline 76) | **76** — back at baseline |
| Test lines added | — | **+1,796** |

Commits: `1206a1ca` baseline · `08d68634` readiness allowlist · `1d8ba3ab` predicate IDs +
authority gating · `44daf404` docs · `d754f220` scope routing + bulk stock · `7974f7bf` UUID
trace fix · `add64275` scoped evidence + router extraction · `50752a8b` docs.

---

## 2. DONE — verified independently

### 2.1 My #1: the catalog candidate universe (the biggest one)

`case_catalog_candidates.py` now builds a typed `CatalogScope` with
`source ∈ {buyer_explicit, tenant_primary, validated_client_context, unresolved}` and
`client_context_disposition ∈ {not_supplied, accepted, overridden, rejected}`. The client
handle is checked with `sells_within()` before it is trusted, and `primary_sold_node()`
provides a **server-derived fallback**.

Measured against the live demo database:

| Buyer purpose | No client handle | With `el-6-6` |
|---|---|---|
| `is 3000 enough for pragmata?` | **eligible, 11 configs**, `tenant_primary` | eligible, 11, `validated_client_context` / accepted |
| `tarae recommended specs, is 3500 enough` | **eligible, 11**, `tenant_primary` | eligible, 11 / accepted |
| `gaming laptop under 3000` | **el-6-11-2, 11 configs** | el-6-11-2 / overridden |
| `I need a desktop workstation for CAD…` | **el-6-3, 2 configs** | el-6-3 / overridden |
| `show me servers for our warehouse` | **el-6-2, out_of_category** | out_of_category |
| `I need a standing desk` | fr-12-1-2, out_of_category | out_of_category |

Every failure mode I reported on 09-04 is gone: the no-handle zero, the *Gaming Laptops*
collapse (fixed by a narrow, explicitly-reasoned `laptop_family = {el-6-6, el-6-11-2}`
equivalence), the silent desktop→laptop substitution, and the `server → el-6-4`
*Handheld Devices* mis-map (**now `el-6-2` Computer Servers**).

Also hardened: `project_accepted_catalog` no longer accepts `None` as "enumerate the whole
tenant catalog" — every caller, administrative previews included, must supply its candidate
set. The unbounded-preview bypass is gone.

### 2.2 My #2: "Did you mean X?" now converges

`clarification_state.py` handles `confirm_canonical_identity` at three sites:

- **Chip click** — `AmbiguityExplorationPanel` → `App.tsx:3787 onConfirmIdentity` →
  `nqeSelection {question_id: 'confirm_canonical_identity', option_id}`.
- **Free text** — `yes` / `yes please` / `correct` / `confirmed` / `that's it`, and the
  negative forms `no` / `incorrect` / `wrong` / `that's not it`.
- On accept the effective query is rewritten to
  `"I need hardware that can run {title}. The buyer confirmed this canonical identity."`;
  on reject, `"The buyer rejected the proposed identity {title}. Ask for the exact product title."`

The loop is closed end to end. This was the top gap for ambiguous titles.

### 2.3 My #6: the fuzzy-identity over-accept band is closed

`_identity_subject_match` now returns **False** for a single-token fuzzy match at any
similarity, with `basis: cited_spelling_correction` — which still routes to the ≥0.65
confirmation branch. Multi-token now requires `len(overlap) >= max(1, n-1)` (was `max(0, …)`),
so it cannot accept with zero literal overlap.

Measured:

| Cited title | Buyer text | Similarity | Before | Now |
|---|---|---|---|---|
| `PRAGMATICA` | "…pragmata…" | 0.8889 | **auto-accept** | confirm |
| `Valheim2` | "…valheim…" | 0.9333 | **auto-accept** | confirm |
| `The Blood of Dawnwalker` | "…bloodwalker…" | 0.6667 | confirm | confirm |
| `PRAGMATA` | "…run pragmata at 1080p" | — | accept | accept (`exact_buyer_span`) |

A different game's requirements can no longer be presented as verified official without a
buyer confirmation.

### 2.4 My #3: the certificates can now fail on an empty shelf

The pragmata test hard-asserts `accepted_claim_count > 0` **and then**
`shelfProducts.length > 0` — the `if` guard is gone. The where-winds-meet continuation
asserts shelf products `> 0`. A new test asserts the opposite direction: partial
requirements must yield `catalog_authority: 'blocked'` and `products == []`. The suite can
now fail in both directions. *(Residual: the A–H battery still has no positive product
assertion — its only change was the two-phase response handler.)*

### 2.5 My #8 and the ratchets

- All four previously-failing tests now pass (`router_refine` num_predict, the feature-flag
  test since renamed, `chat_multimodal_trace_events`, `shopping_case_trace_reader`).
- `test_exception_swallowing_ratchet` — **passes**; `chat.py` back to 76 broad catches.
- `test_async_shopping_case_db_boundary` — **passes**; synchronous interpretation/DB work
  moved off the ASGI loop.
- Size guard: `admin.py`, `core.py` and `turn_router.py` now pass their ceilings via **real
  extraction**, not raised limits — `case_patch_grounding.py` (259 ln), `turn_outcome.py`
  (300 ln), `observability/stage_timer.py`, `timescale_admin.py`. `turn_router.py` shrank
  from 3,249 → **2,801**.

### 2.6 Three findings closed that predate this arc

**(a) The Cairns intake-boundary defect (2026-08-24) is closed.** Case-patch grounding was
substring-based, dropping the demo's own numbers. It now routes through canonical grammars —
`parse_budget`, `classify_budget_scope`, `quantity_value_mentioned` — and emits a typed
rejection receipt with a named `rejecting_predicate`. Measured:

| Utterance | Patch | Before | Now |
|---|---|---|---|
| `AUD 220,000` | budget 22000000 | **dropped** | accepted |
| `we have $220k` | budget 22000000 | **dropped** | accepted |
| `we need 1,200 units` | quantity 1200 | **dropped** | accepted |
| `move five to Cairns` | quantity 5 | **dropped** | accepted |
| `budget is 3000 total` | budget 500000 | — | **rejected** `canonical_budget_grammar` |

**(b) A live secret leak in `/readyz`.** `config.contract` was exposing API keys and
database/Redis connection strings. Verified on the running instance: 8,787 bytes, **zero**
occurrences of `api_key`, `postgres`, `redis://`, `secret` or `password`; `config.contract`
now carries 7 allowlisted non-sensitive fields.

**(c) UUID corruption in the decision trace.** Privacy scrubbing was rewriting
`sc-48504246-…` as a phone-redacted string, making recorded research plans unreachable. Now
six named reference fields bypass scrubbing, and only for syntactically valid UUIDs.

### 2.7 Other verified repairs

- **Per-predicate claim IDs** — `structured_requirement_claims.py` hashes provider, record,
  origin, attribute, operator, value, unit, class, caveat and source revision. Order-stable,
  value-sensitive. Fixes claim collisions (the observed "RAM 8 displaying as 2").
- **Partial requirements cannot qualify** — `gate_terminal_catalog_projection` blocks on
  `permitted + partial`, with explicit narration ("requirements coverage remains partial…").
  Verified: `permitted+complete → qualified`, `permitted+partial → blocked, 0 products`,
  `permitted+complete but empty shelf → no_qualified_products`.
- **`router_output_invalid`** — a provider call that succeeds but returns unusable output is
  no longer mislabelled a transport outage, and has its own honest narration.
- **Held-claim narration** (my 09-04 §4.3) — appends a review boundary instead of deleting
  the success sentence, with a covering test.

---

## 3. LEFT — with evidence

### 3.1 NEW: the "computer chair" scope defect — deterministic, no model involved

The receipt attributes the one failing live browser test to a degraded/router problem. It is
not. **I reproduced it with zero model involvement.**

```
_explicit_category("I need an ergonomic computer chair under AUD 500.")
    → fr-7  Furniture > Chairs          ✅ correct

build_case_catalog_candidate_set(same text, any handle)
    → status=eligible, node=el-6 (Electronics > Computers)   ❌ wrong
```

**Mechanism.** Inside the builder, `_explicit_category` is called with a `preferred_handle`
(the validated client context, or the tenant primary). The `related` list is applied as a
**hard filter before ranking**:

```python
related = [row for row in ranked if preferred_handle and _related(row[2].handle, preferred_handle)]
if related:
    ranked = related          # ← discards fr-7 entirely
```

"computer" matches `el-6` (Computers), which is an ancestor of `el-6-6` and therefore
`_related`. So the **attributive modifier wins and the head noun is discarded**, and the
`purchase_objects` fallback (which would have caught "need … chair") is never reached because
it only runs when `related` is empty. The buyer asks for a chair and is scoped to Computers,
`status=eligible` — so the off-catalog refusal never fires.

**Fix direction:** make `related` a ranking *preference*, not a filter — or rank head-noun
position above context relatedness. Any longer/head match should survive the preference step.

### 3.2 NEW: a test writes to the tracked config file and poisons the suite

`tests/utils.write_feature_flags()` defaults to `path=os.path.join("config", "feature_flags.json")`
— **the real, tracked repo file** — merges test flags into it and **never restores**. Six test
files use it; **none** restore.

Consequences, all measured:

- The one dirty file in the tree is `config/feature_flags.json`, and its diff is
  **substantive**: it *adds* `HIPPOGRAPH_FEEDBACK_ENABLED: true`,
  `RANKING_NUDGE_EXPERIMENT_ENABLED: true`, `RANKING_NUDGE_CANARY_FRACTION: 1.0`, and *removes*
  `DECISION_LOG_WRITES_ENABLED`, `EXTERNAL_RESEARCH_ENABLED`,
  `STEAM_REQUIREMENTS_LIVE_ENABLED`, `TEST_FORCE_BAD_SKU` and the `pricing` capability block.
- `SHOPSQUIRE_CONSOLIDATION_CHECKPOINT_2026-09-07.md` states this file "has no substantive Git
  diff". **That is incorrect** — `git diff` shows a 20-line change.
- It causes **4 reproducible failures**: `test_frontend_backend_parity::test_top_level_contract`
  ×3 ("hippograph feedback must be flag-gated (absent by default)") and
  `test_hippograph_feedback_wiring`. Pointing `FEATURE_FLAGS_PATH` at the committed content
  makes the 3 parity tests pass — proving the dirty file is the cause.
- The suite is now **order-dependent**: one full sweep of `tests/services` + `tests/integration`
  passed clean; a second run of the same command produced these 4 failures.

**Fix:** default `write_feature_flags` to `tmp_path` and require callers to pass an explicit
path; or wrap it in a fixture that snapshots and restores. Then restore
`config/feature_flags.json` from HEAD.

### 3.3 Still open from my previous list

| # | Item | Status | Evidence |
|---|---|---|---|
| 5 | Trailing target tails before the provider lookup | **open** | `PRAGMATA at 1080p`, `Factory IO locally`, `MIO Memories in Orbit well` still reach the connector; `_title_matches` is contiguous-substring so these miss the 0 ms path |
| 7 | Decouple the reconciler from free-text `description` substrings | **open** | no `concept_id` anywhere; unknowns still matched by `_phrase_in(description, span)` |
| — | `chat.py` growth | **open, worsening** | **5,823 lines** (ceiling 5,049) — up 14 since the receipt was written. `shopping_cases.py` 2,397 (2,073), `fulfillment_cases.py` 2,574 (2,447) |
| — | A–H battery positive product assertion | **open** | only the novel-title spec asserts delivery |
| — | Budget `around` mode | **open (product decision)** | `on a 2500 laptop` → min 2,000 / max 3,000 |
| — | `laptop_family` is a hardcoded pair | **residual** | `_related("el-6-3", "el-6-11-1")` is `False` — Gaming Desktops will hit the same collapse |
| — | `recommendation_status` computed but unused | **minor** | present in `terminal_outcome`; zero frontend references |
| 9 | Rockwell human source review | **open (yours)** | still 1 of 20 sources pending |
| — | Full A–H zero-retry matrix; hosted/clean-PostgreSQL certification | **open** | never run green |
| — | Live model not resident | **open (ops)** | `/api/ps` → `{"models":[]}`; next live turn is a ~9.6 GB cold load into 12,227 MiB |

---

## 4. Current health

| Suite | Result |
|---|---|
| `tests/architecture` | **1 failure** (was 3) — size guard only, 3 breaches (was 6) |
| `tests/services` + `tests/integration` | **0 failures** in one ordering, **4** in another — §3.2 |
| Previously-failing four | all pass |
| Scope/candidate probes | all pass (§2.1) |
| `/readyz` secret scan | clean, verified live |

---

## 5. What to do next, in order

| # | Item | Why | Owner |
|---|---|---|---|
| 1 | **Fix `_explicit_category`'s `related` filter** — preference, not filter | This *is* the failing live chair test; the current diagnosis points at the wrong layer | code |
| 2 | **Stop `write_feature_flags` writing to the tracked config**, then restore the file from HEAD | Removes 4 failures, the order-dependence, and a false "clean tree" signal | code |
| 3 | **Extract from `chat.py`** — turn reducer / research entry / terminal projection | It is the only file still growing; the extraction pattern is now proven three times over | code |
| 4 | **Trim trailing target tails** before the provider call | Puts PRAGMATA / Factory IO / MIO on the fast path | code |
| 5 | **Carry a `concept_id`** on material unknowns instead of matching descriptions | Removes the last free-text coupling in the reducer | code |
| 6 | **Generalise the `laptop_family` pair** into a reviewed equivalence table | Gaming Desktops will fail the same way | code |
| 7 | **Add a positive shelf assertion to the A–H battery** | Delivery is only asserted in one spec | test |
| 8 | **Rockwell source sign-off**, or make the hold advisory | 1 of 20 sources; unblocks enrolled-source turns | **user (policy)** |
| 9 | **Pre-load the model, then run the full A–H matrix zero-retry** | The only remaining certificate | **user (ops)** |

---

## 6. Method

**Ran:** full re-derivation of every 09-04 probe against current code — the reconciler and
terminal gate across 6 payload shapes, `_identity_subject_match` across 6 adversarial pairs,
`_purpose_spans`, `parse_commercial_terms` / `parse_budget`,
`build_case_catalog_candidate_set` against the live demo DB with and without a client handle,
`_evaluate_bounded_case_patches` against the Cairns corpus; assertion-level reads of both
Playwright specs; the architecture ratchets and the size guard; a live `/readyz` secret scan;
two full `tests/services` + `tests/integration` sweeps; and a `FEATURE_FLAGS_PATH` controlled
experiment to isolate §3.2.

**Did not run: a live model turn.** `/api/ps` reports no resident model, so any probe pays a
full cold load — the condition behind the 09-03 `0x133` and 09-04 `0x116` bugchecks. Every
claim above is code-derived, offline-executed, or read from the running process's HTTP
surface; none depends on a live inference run.
