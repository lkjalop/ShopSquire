# ShopSquire — Round #6 Delta Assessment & External-Search Product-Selection Audit

**Date:** 2026-09-04 (evening) · **HEAD:** `be3382b9` + uncommitted round-#6 delta
**Prior document:** `docs/SHOPSQUIRE_EXTERNAL_SEARCH_DELTA_VERIFICATION_2026-09-04.md` (round #5)
**Question asked:** verify progress since the last check, assess end to end, and judge whether
external search can pick **the right product** from an ambiguous game or software name.

---

## 0. Verdict

Round #6 is the best delta of this arc. Every one of the six code-owned items on my round-#5
fix list has a real implementation, and the two I called *inverted* or *half-fixed* are now
genuinely fixed and reproducible offline. The governance story is strong: identity is clamped
to cited rows, low-confidence identity now asks instead of guessing, router truncation raises
instead of being narrated as catalog fact, and the auxiliary-title filter kills the
"Witcher 3 REDkit" class of wrong answer.

**The buyer-outcome story is still not closed, and the reason has moved.** It is no longer
`semantic_resolution` disagreeing with the provider — that is fixed. It is now the **catalog
candidate universe**, which is selected by a *client-supplied taxonomy handle* rather than by
the resolved workload. The buyer UI hardcodes `'el-6-6'` (Laptops) on every turn. Remove that
constant — or ask for a gaming laptop, a desktop, or a workstation — and the candidate set is
empty and the shelf is empty **no matter how perfectly the research succeeded**.

That one mechanism explains, exactly, the 0-product pattern I measured on 09-04: every turn
containing the word *laptop* returned products; every turn without it returned zero. It was
never the research. It was the shelf's input set.

Second-order, and the reason this survived five green rounds: **the live certificates cannot
fail on an empty shelf.** Across five novel-title tests and eight A–H scenarios there is
exactly one product-existence assertion, and it sits inside an `if` that skips itself when the
run produces no accepted claims.

---

## 1. What actually changed since my last check

| | Round #5 (my last assessment) | Round #6 (now) |
|---|---|---|
| Tracked files modified | 39 | **43** |
| Line delta | +1,337 / −136 | **+2,060 / −209** |
| New untracked files | 4 | **12** (4 modules, 1 React panel, 4 tests, 2 docs, 1 misc) |
| Committed | no | **still no** — 44 modified, 12 untracked |

**New in round #6**

- `src/app/services/terminal_research_reconciliation.py` (211 ln) — the Fix-#1 reducer.
- `frontend/src/components/ArchitectureAlternativesPanel.tsx` — desktop/mobile alternatives.
- `tests/services/test_terminal_research_reconciliation.py`, `…_narration.py`,
  `test_case_catalog_trace_binding.py`, `test_semantic_coverage_subject_spans.py`.
- Substantial edits: `turn_router.py` (+232), `shopping_case_open_world_research.py` (+302),
  `chat.py` (+290), `open_world_identity_resolution.py` (+69), `semantic_coverage.py` (+63),
  `steam_requirements.py` (+36), `router_model_call.py` (+50).

---

## 2. Scorecard against my round-#5 fix list

| # | Item from the 09-04 doc | Status | Evidence |
|---|---|---|---|
| 1 | Reconcile `semantic_resolution` with structured-provider resolution | ✅ **Done** (4 caveats, §4.1) | `terminal_research_reconciliation.py`; wired `chat.py:3816`, `:4505`; gate `:4531` |
| 2 | Clamp the concept span before any provider lookup | ✅ **Done** (1 caveat, §4.2) | `semantic_coverage.py:_sanitize_subject_span`; both Where-Winds-Meet phrasings now yield the clean span |
| 3 | Narration precedence — a concluded outcome outranks a router failure | ✅ **Done** (new contradiction, §4.3) | `terminal_research_narration.py:44-55` `research_concluded` guard |
| 4 | Router recall on `"will a $3000 laptop run <title>?"` | ✅ **Done** (offline) | new `run\|play\|use` purpose pattern; router `unresolved_entities`; relation-anchored repair prompt |
| 5 | Quantity guard on grammatical number | ✅ **Verified fixed** (side effect, §4.6) | `commercial_terms.py` budget-span-overlap + currency-prefix guards |
| 6 | Low-confidence identity → "Did you mean …?" | ✅ **Emitted** — ❌ **not answerable** (§4.4) | `open_world_identity_resolution.py:332`; `shopping_case_open_world_research.py:740-760` |
| 7 | R12 — sign off Rockwell or make the hold advisory | ⛔ **Open (user/policy)** | 1 of 20 sources pending, §3 |
| 8 | Add a non-instructive case to the certificate | ✅ **Done** | `live-novel-title-intelligence.spec.ts:137` uses the exact A-T2 phrasing |
| 9 | Ops: make certification survivable | 🟡 **Partial** | `playwright.config.ts` honours `PLAYWRIGHT_DISABLE_GPU`; nothing caps resident models — and the 09-04 bugcheck had **no browser running** |
| 10 | Commit the delta | ⛔ **Open** | 2,060 lines uncommitted, now through two bugchecks |

**6 of 6 code-owned items implemented.** Items 7, 9 and 10 are yours; 10 is now the single
largest avoidable risk on the project.

Bonus, unprompted and correct: **N2 is properly closed.** `router_model_call.py` raises a typed
`RouterOutputTruncated` on `done_reason == "length"` and raised the generation budget 320 → 768.
That was the defect that let a truncated router response be narrated as a catalog fact.

---

## 3. Verification of the round-#6 handoff claims

### Verified true

| Claim | How I checked |
|---|---|
| Low-confidence identity → "Did you mean The Blood of Dawnwalker?", blocked authority, no fetch, empty shelves, no commerce | `_identity_subject_match` gives `similarity 0.6667 ≥ 0.65` → `confirmation_required`; `gate_terminal_catalog_projection` forces `products=()`, `product_shelves=None`, `catalog_authority="blocked"` |
| Accepted provider evidence recovers from a timed-out/empty semantic router when the identity is literally in the buyer's turn | Reproduced: empty `concepts` + empty `material_unknowns` + literal buyer text → `proceed_catalog` / `permitted` |
| Research overrides the earlier unresolved state through the terminal reducer without rerunning the core | `chat.py:4505` reconciles post-research; `core_invocation_count` stays 1 |
| BG3 → Rockwell retains AUD 3,000 while clearing BG3 evidence | `budget_grammar.canonical_budget_from_accepted_slots`; `test_chat_additive_workload_continuation` passes |
| A–H harness waits for the completed two-phase response | `send()` in both specs resolves only on `status !== 'in_progress'` |
| Launcher removes stale listeners/workers and refuses to serve an old backend | `start_recording_stack.ps1`: port sweep + command-line match + **`throw` on a foreign port owner** + `--hostname=shopsquire-recording-` worker sweep. Fail-closed, good design |
| Exactly one API and one Celery worker | Confirmed live — uvicorn PID 7492, celery PID 38036, plus the 8099 handoff receiver |
| Focused tests pass | Re-ran: **44 pass** (new reducer, narration, trace binding, spans, research outcome, budget parity) · **96 pass** (all eight modified test files) · **8/8** frontend component tests |

### Verified with a material caveat

| Claim | Caveat |
|---|---|
| "Live novel-title browser certificate: 5/5 passed" | True — but see §5. The suite has **one** product-existence assertion and it is conditional. 5/5 green is compatible with an empty shelf on four of the five |
| "Rockwell returned 16 held claims and the correct review blocker" | Consistent with the code; but held-claim narration **deletes** any qualified-product sentence even when accepted claims and a permitted catalog coexist (§4.3) |
| "All six Decision Trace tabs opened without 404s" | The assertion is `not toContainText(/404\|not found/i)` — proves absence of 404 text, not that each tab rendered its evidence |
| "Broader recommendation/research regression slice passed" | The **full** `tests/services` + `tests/integration` sweep I ran here has **4 failures**, all attributable to this arc (§3.1) |

### Needs correcting

| Claim | Correction |
|---|---|
| "Independently review the **eight** pending source origins" | `config/official_workload_sources.json` holds **20** sources; exactly **one** carries an `independent_review` block — `rockwell_emulate3d_official_requirements`, status `automated_policy_checks_passed_human_signoff_pending`. If "eight" means held *claims* from one fetch, say so; as written it implies eight policy decisions where there is one |
| "Ollama `qwen3:14b` resident on GPU for ~30 minutes" | Not true at audit time: `GET /api/ps` returned `{"models":[]}`. The model has been evicted, so the next live turn pays a full ~9.6 GB cold load — the exact condition behind both bugchecks |

### 3.1 · The four red tests

| Test | Failure | Attribution |
|---|---|---|
| `test_router_refine.py::test_router_default_generation_budget_fits_bulk_decision` | `assert 768 == 320` | **This uncommitted delta.** The N2 fix raised `ROUTER_NUM_PREDICT` 320 → 768 and left the old assertion behind. The code is right; the test is stale |
| `test_feature_flag_env_overrides.py::…fulfillment_defer_env_override` | `KeyError: 'FULFILLMENT_DEFER_TO_CART'` | Committed `f2244313` removed the flag from `config/feature_flags.json` without updating its test |
| `test_chat_multimodal_trace_events.py::…multimodal_and_intent_routing_events` | HTTP 503, sqlite `no such table: conversation_case_state` / `search_events` | Committed `f2244313` introduced `conversation_case_state`; this integration test's schema fixture never creates it |
| `test_shopping_case_trace_reader.py::test_case_marker_cannot_cross_tenants` | fails in the sweep, **passes in isolation** | Order-dependent / shared-state flake, not a real defect |

Three of four are one-line fixes. None invalidate the delta — but "the regression slice passed"
should be stated as "the *selected* slice passed".

---

## 4. Findings

### 4.1 · The reconciler works, and has four ways to stay blocked

`reconcile_semantic_resolution` is the right idea in the right place. I exercised it directly
with seven payload shapes:

| Scenario | `requirements_established` | outcome | catalog |
|---|---|---|---|
| Concept span == provider `requested_name` | true | `proceed_catalog` | **permitted** |
| Concept span **shorter** than `requested_name` | **false** | clarify | blocked |
| Buyer said `tarae`, provider `requested_name` = canonical `TARAE: The Unbound` | **false** | clarify | blocked |
| Resolved concept **+ one buyer-owned unknown** | true | clarify | **blocked** |
| Resolved concept + research-owned unknown whose `description` omits the span | true | clarify | **blocked** |
| Empty semantic (router timeout) + literal buyer text | true | `proceed_catalog` | **permitted** |
| Two concepts, one resolved | true | clarify | blocked |

Four consequences worth naming:

1. **Binding is one-directional.** `_phrase_in(anchor, name)` requires the *provider's*
   `requested_name` to sit inside the *router's* concept span. The two come from different
   producers — the core's `workload_entities` vs `coverage_abstention_shadow.concepts` — so the
   reverse case (entity longer than span) silently fails to bind.
2. **String coupling on free text.** A research-owned unknown only clears when the resolved span
   is a literal substring of its `description` (`terminal_research_reconciliation.py:149`).
   Router-generated unknowns are safe because this delta writes
   `f"Canonical identity and requirements for {unknown}"`. **Model-authored unknowns are not.**
   This is the same substring-grounding pattern that caused the Cairns intake regression; it
   will drift the next time prompt wording changes. Carry a `concept_id` instead.
3. **One unrelated unknown re-blocks everything.** Any material unknown the buyer owns (screen
   size, weight, brand) keeps `catalog_authority: blocked` even with complete verified official
   requirements. Defensible governance — but it means the shelf appears only on turns where the
   router emits exactly one concept and zero other unknowns.
4. **The degraded path is more permissive than the healthy path.** A timed-out router (no
   concepts at all) grants `permitted`; a working router that emits one extra unknown grants
   `blocked`. It is bounded by the literal-buyer-text check so it is not unsafe, but the
   asymmetry is backwards and will confuse anyone reading the trace.

### 4.2 · Span hygiene is fixed for the cases that failed — with one live-path caveat

Verified offline against `_purpose_spans`:

| Buyer turn | Concept span |
|---|---|
| `will a $3000 laptop run where winds meet?` | `where winds meet` ✅ (was: nothing at all → `discovery: not_attempted`) |
| `what about for where winds meet is 3000 ok?` | `where winds meet` ✅ (was: `where winds meet is 3000 ok`) |
| `Could a laptop under AUD 2,500 run PRAGMATA at 1080p?` | `PRAGMATA at 1080p` 🟡 |
| `I need a workstation that can run Factory IO locally.` | `Factory IO locally` 🟡 |
| `…to play MIO Memories in Orbit well?` | `MIO Memories in Orbit well` 🟡 |

The sanitizer subtracts **only** the budget span. Trailing target and adverbial words survive,
and `steam_requirements._title_matches` is a **contiguous substring** test
(`requested_norm in resolved_norm`), so `"pragmata at 1080p"` can never match `"PRAGMATA"`.
Those turns fall through to the slower open-web ladder — which is why PRAGMATA cost 6.2 s on
09-04 while `where winds meet` resolved in 0 ms.

**Fix:** trim trailing render-target / adverbial tails (`at <res>`, `locally`, `well`,
`smoothly`) before the provider call, or have the provider retry progressively shorter prefixes.
Do not add a title list.

### 4.3 · Held claims still delete a truthful success sentence

`terminal_research_narration.py:57` overwrites the assistant message whenever
`held_claim_count > 0`, regardless of accepted claims or catalog authority. Reproduced:

```
input : accepted 2, held 3, catalog_authority = permitted,
        message = "Four qualified laptops meet PRAGMATA's official minimums under AUD 2,500."

output: "I found the official source for PRAGMATA and parsed 5 cited requirement claims.
         3 claims remain held pending independent human source-policy review.
         Recommendations may be explored only as provisional; no product is verified
         and no cart or supplier action was authorized."
```

The shelf renders (`materialProductFitBlocked` is false once accepted claims exist) while the
prose says no product is verified. The N8 inversion was fixed for router failures and reappeared
for held claims. **Fix:** make the held sentence *additive* when `accepted_claim_count > 0` and
`catalog_authority == "permitted"`; keep it replacing only when accepted == 0. No test covers
accepted > 0 ∧ held > 0 today.

### 4.4 · "Did you mean X?" is a dead end

`confirm_canonical_identity` is **emitted and never consumed.** Across `src/` and `frontend/src/`
the id appears only where it is written (`shopping_case_open_world_research.py:755`,
`research_outcome.py:327`). There is no affirmation handler in `chat.py`, no persistence of the
proposed identity against the case, and no UI control that accepts it.

A buyer who answers *"yes"* sends a turn containing no title. The case purpose still holds the
misspelling, so the same `confirmation_required` fires again. The only escape is retyping the
correct title — at which point the disambiguation cost a turn and delivered nothing.

For the question you actually asked, this is the highest-value gap: it is precisely the
*ambiguous name* case.

### 4.5 · The fuzzy-identity gate has a cliff and an over-accept band

`_identity_subject_match` (`open_world_identity_resolution.py:131-167`) uses
`difflib.SequenceMatcher` with two thresholds: **≥ 0.86** auto-accepts as a spelling correction,
**≥ 0.65** asks for confirmation, below that rejects.

| Buyer token | Cited title token | Ratio | Behaviour |
|---|---|---|---|
| `bloodwalker` | `dawnwalker` | 0.6667 | confirm — **1.7 pp above the reject cliff** |
| `pragmata` | `pragmatica` | 0.8889 | **auto-accept** |
| `valheim` | `valheim2` | 0.9333 | **auto-accept** |
| `dyinglight` | `dyingnight` | 0.9000 | **auto-accept** |
| `hades` | `hades ii` | 0.7692 | confirm ✅ |
| `factorio` | `factorial` | 0.8235 | confirm ✅ |

Two problems in one function. The certified case sits 0.017 above the reject threshold — a
slightly different misspelling drops it to `rejected` with no "did you mean" at all. And for
**single-token titles** the overlap requirement collapses
(`len(overlap) >= len(title_terms) - 1` → `0 >= 0`), so a genuinely *different* nearby title
auto-accepts as a grounded identity and its requirements are then presented as verified
official. Multi-word titles can never auto-accept — that is the correct end of the same rule;
the asymmetry is the bug. The candidate must be grounded in a cited row, which is exactly when
confusable sequels and spin-offs appear, so this is a live risk rather than a theoretical one.

**Fix:** require the spelling-correction band to also be the *only* candidate above threshold
among the cited rows, and route single-token near-misses to confirmation rather than acceptance.

### 4.6 · Quantity is fixed; the budget widened

`"on a 2500 laptop"` → `quantity=None` ✅ (was 2500 — the N4 residual). But `budget_grammar` now
reads that phrasing as `mode="around"`, `budget_min=2000`, `budget_max=3000`: a buyer who said
2500 authorises a shelf up to 3000. That is the pre-existing meaning of `around`; this delta
extended the pattern to `on a` / `for a` phrasings, so more turns land in it. Confirm that
reading is intended before certification — it is a budget-truth statement, and this project has
a documented history of budget parsers drifting apart.

### 4.7 · The real reason shelves are empty: the candidate universe

This is the headline finding. `project_accepted_catalog` receives `candidate_configuration_ids`
from `build_case_catalog_candidate_set`, and an **empty list means zero products, never the
whole catalog** (`accepted_catalog_projection.py:447-451` — deliberate, and correct). That list
comes from a taxonomy node chosen as:

```
explicit product-category phrase in the buyer's purpose
   OR   storefront_taxonomy_handle supplied by the CLIENT
   ELSE unresolved  →  configuration_ids = []  →  zero products
```

Measured `_explicit_category` results:

| Buyer purpose | No client handle | With `el-6-6` |
|---|---|---|
| `is 3000 enough for pragmata?` | **None → 0 products** | None → falls back to Laptops |
| `tarae recommended specs, is 3500 enough` | **None → 0 products** | None → Laptops |
| `what about for where winds meet is 3000 ok?` | **None → 0 products** | None → Laptops |
| `will a $3000 laptop run where winds meet?` | el-6-6 | el-6-6 |
| `gaming laptop under 3000` | **el-6-11-2 (Gaming Laptops)** | el-6-6 (Laptops) |

This reproduces my 09-04 live table exactly: every turn containing *laptop* returned products;
every turn without returned zero. **The 0-product result was never a research failure.**

Four distinct issues sit here:

1. **The buyer UI hardcodes the answer.** `App.tsx:1851` (pre-existing) and `App.tsx:2156`
   (**new in this delta**) both send `storefront_taxonomy_handle: 'el-6-6'`. It is commented as
   an intentional pinned-storefront demo constraint, which is fair — but product scope is now a
   client constant, and **any other caller** (an API probe, an integration, a partner, a future
   channel) gets zero products on exactly the novel-title turns this arc exists to serve. The
   server should derive or default this, not trust the client for it.
2. **The query taxonomy is finer than the configuration taxonomy.**
   `_derived_configuration_handle` maps every laptop-shaped configuration to `el-6-6`, but a
   buyer saying "gaming laptop" resolves `el-6-11-2`, and `_related` is ancestor-only. So
   *without* the hardcode, `"gaming laptop under 3000"` selects a node **no configuration can
   ever match** → empty shelf. The client constant is silently papering over a taxonomy
   mismatch.
3. **Desktops and servers are worse.** `"I need a desktop workstation…"` and `"show me
   servers…"` both resolve `explicit=None`, so with the pinned handle they are silently scoped
   to **Laptops** — the buyer asks for a desktop and gets laptops, with no `out_of_category`
   refusal, because the phrase never matched a node at all. Battery scenario F ("compare desktop
   and mobile workstation options") sits directly on top of this.
4. **Pre-existing mis-map (committed `448c630a`, not this delta):**
   `case_catalog_candidates.py:120` maps `form == "server"` → **`el-6-4`**, which is
   `Electronics > Computers > Handheld Devices`. The server node is `el-6-2`
   (`Electronics > Computers > Computer Servers`). Every server configuration is currently
   classified as a handheld device.

---

## 5. What the certificates can and cannot fail on

I read both live specs assertion by assertion.

**`live-novel-title-intelligence.spec.ts` — the "5/5"**

| Test | Asserts a product exists? |
|---|---|
| mio | no |
| pragmata | **only inside** `if (scenario.name === 'pragmata' && accepted_claim_count > 0)` — skips itself on a zero-claim run |
| dawnwalker | no |
| where-winds-meet continuation | asserts `catalog_authority === 'permitted'` and accepted > 0 — **not** that any product rendered |
| low-confidence dawnwalker | asserts **zero** products (correct negative) |

**`live-external-search-battery.spec.ts` — A–H**: no scenario asserts a non-empty shelf.
Scenario D asserts `products` has length 0.

So there is **exactly one conditional product-existence assertion across thirteen live
scenarios.** The suite proves identity, authority, revision binding and fail-closed behaviour —
all genuinely valuable — but it cannot fail when the buyer sees nothing. That is why the
0-product regression survived five green rounds.

**Cheap, high-value fix:** make the pragmata and where-winds-meet assertions unconditional —
`catalog_authority === 'permitted'` ⇒ `shelfProducts.length > 0` — and add one API-level
scenario that sends **no** `storefront_taxonomy_handle`, so the client constant cannot hide the
candidate-set defect.

---

## 6. So — can it pick the right product from an ambiguous game or software name?

**Identifying the right *title*: yes, and it is now genuinely good.** The ladder is:

```
router (clamped to exact buyer spans; unresolved_entities is first-class)
  → deterministic purpose spans, budget span subtracted
  → enrolled structured provider (Steam): contiguous title match,
    auxiliary artefacts (redkit / demo / dlc / sdk / soundtrack / benchmark …) rejected
  → open-web discovery → LLM identity proposal
  → grounded-in-cited-rows clamp → buyer-subject match
  → ≥ 0.86 accept · ≥ 0.65 confirm · else reject
  → official-origin fetch only if authorised and enrolled
```

Every rung refuses rather than infers. `select_live_store_item` closes the "Witcher 3 REDkit"
wrong-identity class I measured on 09-03. Unreleased titles produce an honest refusal instead of
a fabricated budget verdict. That is a real, defensible capability and it is the hard half.

**Turning the right title into the right *product*: not yet.** Ranked by how often each will
bite a real buyer:

| Rank | Defect | Effect on product choice |
|---|---|---|
| 1 | Candidate set comes from a client taxonomy constant (§4.7) | Empty shelf on every turn without a category noun; **desktop / server requests silently served laptops** |
| 2 | "Did you mean X?" cannot be answered (§4.4) | Ambiguous names dead-end instead of converging |
| 3 | Any extra material unknown re-blocks a permitted catalog (§4.1.3) | Shelf appears only on single-concept, zero-unknown turns |
| 4 | Trailing target tokens defeat the provider title match (§4.2) | Slow path or no structured resolution for natural phrasings |
| 5 | Single-token fuzzy auto-accept (§4.5) | Can present a *different* game's requirements as verified official |
| 6 | Held-claim narration deletes the success sentence (§4.3) | Correct products described as unverified |

Fix 1 and 2 and the demo moves from "correct refusals" to "correct answers".

---

## 7. What to do next, in order

| # | Item | Why this order | Owner |
|---|---|---|---|
| 1 | **Derive the candidate universe server-side.** Default the storefront handle on the server; make `_derived_configuration_handle` and the query taxonomy agree (or make `_related` sibling-aware under a shared parent) so `el-6-11-2` and `el-6-6` can both match laptops. Fix the `server → el-6-4` mis-map to `el-6-2` | Removes the actual 0-product cause and the client's ability to hide it | code |
| 2 | **Make `confirm_canonical_identity` answerable.** Persist the proposed identity on the case; accept a yes/no or a chip click; bind it to the next revision | Closes the ambiguity loop this whole arc exists to serve | code |
| 3 | **Un-guard the shelf assertions** in the two live specs; add one API scenario with no `storefront_taxonomy_handle` | Until this exists the suite cannot fail on the thing that is broken | test |
| 4 | **Held-claim narration becomes additive** when accepted > 0 and catalog permitted; add the missing accepted ∧ held test | Truthfulness; roughly a one-line change | code |
| 5 | **Trim trailing target tails** before the provider call, or retry shortening prefixes | Puts PRAGMATA / Factory IO / MIO on the 0 ms path instead of the 6 s path | code |
| 6 | **Tighten the fuzzy gate:** single-token near-miss → confirm, not accept; require uniqueness among cited rows | Prevents a wrong title being certified as verified official | code |
| 7 | **Decouple the reconciler from description substrings** — carry a `concept_id` on the unknown and match on it | Removes the drift trap before prompts change again | code |
| 8 | **Fix the three stale tests** (`num_predict` 320→768, the removed `FULFILLMENT_DEFER_TO_CART` flag, the missing `conversation_case_state` fixture table) | Red tests hide the next real regression | code |
| 9 | **R12 — Rockwell sign-off** (one field, one source of twenty) or make the hold advisory | Unblocks every enrolled-source turn; still yours | **user (policy)** |
| 10 | **Commit the delta.** 2,060 lines across 56 files, through two bugchecks, zero commits | Pure risk, growing every round | **user** |
| 11 | **Ops:** cap resident models during live runs. `qwen3:14b` is currently **not** resident, so the next live turn pays a full cold load into ~2.3 GB of headroom | Two bugchecks in two days; the 09-04 one had no browser, so `PLAYWRIGHT_DISABLE_GPU` does not cover it | **user (ops)** |

---

## 8. Method — and what I deliberately did not run

**Ran:** a static read of the full 2,060-line delta; targeted execution of
`reconcile_semantic_resolution`, `terminal_research_narration`, `parse_commercial_terms`,
`parse_budget`, `_purpose_spans`, the `_identity_subject_match` similarity band,
`_explicit_category` and `_related` against the exact buyer sentences from the 09-04 live table;
an assertion-level read of both Playwright specs; the enrolled-source registry count; live
process and health checks.

**Test results (this session):** 44 pass (new reducer + narration + trace binding + spans +
research outcome + budget parity) · 96 pass (all eight modified test files) · 8/8 frontend
component tests · full `tests/services` + `tests/integration` sweep: **4 failures**, itemised
in §3.1 (three stale, one order-dependent).

**Did not run: a live model turn.** `GET /api/ps` shows **no resident model**, so any live probe
pays a full ~9.6 GB cold load of `qwen3:14b` into a 12,227 MiB card — the exact condition behind
the 2026-09-04 `0x116 VIDEO_TDR_ERROR` and the 2026-09-03 `0x133 DPC_WATCHDOG_VIOLATION`.
Crashing your machine to re-measure something derivable statically is a bad trade. Every claim
above is labelled by how it was obtained, and the A–H matrix re-run remains attended work.
