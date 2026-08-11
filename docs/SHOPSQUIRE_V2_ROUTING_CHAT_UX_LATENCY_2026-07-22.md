# ShopSquire V2 — Routing Demarcation, chat.py Refactor, Latency & UX

**Date:** 2026-07-22 · **HEAD:** a586982 · **Status:** assessment + wiring plan (no code changed)

This doc assesses the V2 routing surface (`route_turn` / `_bounded_fallback_decision`), the
`chat.py` edge, and the UI/UX latency envelope; then gives a wired, test-driven plan to improve
each, with business + architectural trade-offs per roadmap item.

---

## 0. TL;DR

1. **Clarify is not a routing outcome yet — it's a post-retrieval afterthought.** The core asks a
   clarifying question only *after* it retrieves products, and `slot_gap_clarify` explicitly returns
   `None` when there are **no** products ([gates.py:38-39](../src/app/services/recommendation_core/gates.py#L38-L43)).
   That is exactly backwards for the `empty_rate` pain: the moment clarify is most valuable (we found
   nothing) is the moment it's suppressed. **Fix: promote clarify to a first-class, pre-retrieval
   routing decision.**
2. **The router does two jobs in one clamp.** `route_turn` fuses *intent classification* (lane /
   subject_action / procurement_context — must resolve) with *grounding* (taxonomy handle — best-
   effort). A bad handle shouldn't weaken a good lane. **Demarcate them.**
3. **`_bounded_fallback_decision` guesses instead of asking.** On model miss it returns a bare
   `SEARCH` ([turn_router.py:285-295](../src/app/services/recommendation_core/turn_router.py#L285-L295))
   that yields empty/irrelevant results. **Route ambiguous misses to clarify.**
4. **`chat.py` has a *second* router.** `_classify_turn_intent`, `_is_budget_query_text`,
   `_is_deficit_reorder_query`, `_brand_hint_from_text`, `_extract_budget_bounds` are regex intent
   parsers in the edge ([chat.py:202-360](../src/app/routers/chat.py#L202-L360)) that duplicate and
   can drift from the core router — a direct violation of the "never add a second copy of a decision
   surface" doctrine. **Delete them; delegate to the core.**
5. **`_chat_query_impl` is a 1,533-line god-function** ([chat.py:1421-2954](../src/app/routers/chat.py#L1421))
   that also embeds a ~470-line image-CV subsystem ([chat.py:736-1204](../src/app/routers/chat.py#L736-L1204)).
   **Strangle it into a thin edge (~400 lines) + `image_edge.py`.**
6. **Perceived latency, not p95, is the UX metric.** p95 ≈ 7s (router model ≈ 100% of it). You cannot
   hit a 1s budget without streaming + progressive disclosure — but **routing to clarify is
   template-only and effectively instant**, so fixing #1 is *also* a latency win.

---

## 1. Current routing architecture (as-built)

```
POST /chat/query
  └─ chat.py::_chat_query_impl          [3,010-line router; 1,533-line handler]
       ├─ _classify_turn_intent(...)     ← REGEX router #2 (duplicate decision surface)
       ├─ _extract_budget_bounds(...)    ← REGEX budget parse (duplicate of budget_grammar)
       ├─ _cart_mutation_short_circuit
       ├─ image CV extraction (470 ln)   ← misplaced subsystem
       └─ _call_recommend_in_process → recommend.suggest()  [LEGACY 12,604-line executor]
                                            └─ (V2 facade only under RECOMMEND_CORE_MODE)

Facade path (RECOMMEND_CORE_MODE = canary|primary):
  recommendation_facade.py
    ├─ pre_gate (shared commerce guard, run once)
    ├─ route_turn(db, envelope)          [turn_router.py]
    │     model → JSON → clamps(lane∈LANES, handle∈sold, reqs∈registry, brand∈catalog,
    │                           refusal gate) → TurnDecision
    │     on any miss → _bounded_fallback_decision  (GUESSES SEARCH/PROCUREMENT)
    ├─ recommend_turn(db, envelope)      [core.py]
    │     plan → retrieve → fit_check → POST-retrieval stages:
    │       capability_budget · shelf · variant_clarify · complement_offer ·
    │       bulk_economics · fulfillment_preview → slot_gap_clarify (LAST, product-gated)
    └─ write_session (postflight)
```

**Vocabulary that matters:** `LANES` is 10 values
([envelope.py:20-21](../src/app/services/recommendation_core/envelope.py#L20-L21)) — `SEARCH,
FILTER, COMPARE, EXPLAIN, SUPPORT_CLAIM, CART_MUTATE, PROCUREMENT, OFF_CATALOG, POLICY_QUESTION,
INVENTORY`. **`CLARIFY` is not among them.** Clarify is only a *status* on `StageResult`/`CoreResponse`
([envelope.py:227,253](../src/app/services/recommendation_core/envelope.py#L227)) — an annotation the
model never routes to.

---

## 2. Routing demarcation problems (file:line)

| # | Problem | Evidence | Consequence |
|---|---|---|---|
| R1 | Clarify is post-retrieval & product-gated | [gates.py:38-39](../src/app/services/recommendation_core/gates.py#L38-L43) `if not has_products: return None` | Empty results → no clarify → dead-end turn (the `empty_rate` metric) |
| R2 | Router fuses intent + grounding | [turn_router.py:616-642](../src/app/services/recommendation_core/turn_router.py#L616-L642) one JSON, one clamp chain | A wrong handle can drag a correct lane into fallback |
| R3 | Fallback guesses, never asks | [turn_router.py:285-295](../src/app/services/recommendation_core/turn_router.py#L285-L295) `lane="PROCUREMENT" if qty>=2 else "SEARCH"` | Ambiguous → confident-wrong instead of one question |
| R4 | `confidence` captured but unused as a lever | model returns `confidence`; only stored (0.4 on fallback) | No graceful "I'm not sure → ask" band |
| R5 | Second router in the edge | [chat.py:313-360](../src/app/routers/chat.py#L313-L360) | Drift between `chat` and `core` classification |

---

## 3. Proposed V2 routing demarcation

### 3.1 Promote CLARIFY to a routing decision (pre-retrieval)

Add a **required-field contract per lane** and a **pre-retrieval clarify gate**. The rule
(loop-engineering "small loop"): *parse to the fixed schema; if a **required** field for the chosen
lane can't be filled and retrieval would therefore be a guess, ask exactly one bounded question
before spending the retrieval + fit budget.*

```
LANE_REQUIRED_FIELDS = {
    "SEARCH":      [],                     # can run with nothing (browsing is legitimate)
    "FILTER":      ["prior_subject"],      # nothing to filter without a prior slate
    "COMPARE":     ["compare_targets|prior_shortlist"],
    "PROCUREMENT": ["quantity", "budget_scope_if_budget_present"],
    ...
}
```

Decision order becomes:

```
route_turn → TurnDecision
  if decision.confidence < LOW and lane not in ALWAYS_SAFE:  → CLARIFY (band, §3.3)
  elif required_field_gap(decision):                          → CLARIFY (targeted)
  else:                                                        → proceed to retrieve
```

**Key property:** the clarify question is **template-only** (no second model call), so this path is
~single-digit ms — it *removes* a 7s wasted retrieval, not adds latency. Clarify becomes both a
quality win (fewer empty/wrong turns) and a latency win.

### 3.2 Split intent from grounding

Two typed sub-results inside `TurnDecision`, each with its own confidence:

- **Intent** (`lane`, `subject_action`, `procurement_context`) — must resolve; drives control flow.
- **Grounding** (`node_handle`, `requirements`) — best-effort *hint*; a miss degrades grounding to
  "search-broad", never the whole turn.

This makes R2 impossible by construction: a foreign handle can no longer force `_bounded_fallback`
when the lane itself was confidently classified.

### 3.3 Confidence-banded routing (use the field you already have)

| Band | model `confidence` | Action |
|---|---|---|
| High | ≥ 0.70 | Proceed; no hedge |
| Medium | 0.40–0.69 | Proceed **with a soft hedge** in narration ("showing my best read — tell me if I misread") |
| Low | < 0.40 | **Clarify** (one bounded question) or bounded-fallback if a sold node is unambiguous |

### 3.4 Make `_bounded_fallback_decision` clarify-aware

When it cannot find a `sells_within` node **and** the query names no sold category
([turn_router.py:264-265](../src/app/services/recommendation_core/turn_router.py#L264-L265)), return
a `CLARIFY` decision ("I want to get this right — are you after X or Y?") instead of a bare `SEARCH`
that will retrieve nothing. Preserve the grammar-recovered `quantity`/`budget` so the re-parse after
the answer is richer.

### 3.5 Fix the empty-result clarify inversion (R1)

`slot_gap_clarify` should fire **especially** when `has_products` is false and a slot is missing —
"I didn't find a match; is your budget flexible, or should I widen the search?" This is a one-branch
change with immediate `empty_rate` impact and is independently shippable (see §6, TDD-1).

---

## 4. chat.py refactor (strangler-fig, not rewrite)

**Target end-state:** `chat.py` is a **thin transport/presentation edge (~400 lines)**. Its only
jobs: parse request → build `TurnEnvelope` → call the **facade** (not `suggest()`) → format
`CoreResponse` onto the chat wire contract → persist the chat message. Everything else moves out.

| Move | From | To | Why |
|---|---|---|---|
| Delete regex router | `_classify_turn_intent`, `_is_budget_query_text`, `_is_deficit_reorder_query`, `_brand_hint_from_text`, `_extract_budget_bounds` ([chat.py:202-360](../src/app/routers/chat.py#L202-L360)) | core `route_turn` + `budget_grammar` | Kills duplicate decision surface (doctrine) |
| Extract image edge | image-CV block ([chat.py:736-1204](../src/app/routers/chat.py#L736-L1204), ~470 ln) | new `services/image_edge.py` | Cohesive subsystem, wrongly in a router |
| Extract presentation | `_build_anchor_sections`, `_build_right_panel_contract`, `_score_anchor_candidate` ([chat.py:545-716](../src/app/routers/chat.py#L545-L716)) | `services/chat_presentation.py` | Pure formatting ≠ transport |
| Decompose handler | `_chat_query_impl` (1,533 ln) | `ingest() → dispatch() → present()` | God-function → 3 testable units |
| Replace loopback | `_call_recommend_in_process → suggest()` ([chat.py:1351-1401](../src/app/routers/chat.py#L1351)) | facade dispatch | The archive precondition |

**Sequence (safe):** build the thin `dispatch()` behind `CHAT_EDGE_V2` flag → shadow-diff its wire
output against the current handler on live traffic → cut over lane-by-lane → delete the old handler.
This is the same off→shadow→canary ladder the facade already uses, applied to the edge.

---

## 5. Wiring the clarify-first gate (concrete)

No new lane needed — reuse the existing `clarify` channel, but let the **router** populate it and
**short-circuit retrieval**.

1. **`envelope.py`** — add `LANE_REQUIRED_FIELDS` + `required_field_gap(decision) -> list[str]`.
2. **`turn_router.py`** — after clamps, before returning, set `decision.clarify_before_retrieve =
   True` + `decision.clarify = build_clarify(gap|low_confidence)`. Keep it **template-only**.
3. **`core.py::recommend_turn`** — at the top, if `decision.clarify_before_retrieve`: skip
   `retrieve`/`fit`, build a `CoreResponse(status=clarify, clarify=[...], message=<the question>)`,
   `return resp.finalize()`. The `message is NEVER empty` invariant already holds (the question is
   the message).
4. **`facade`** — no change; it already returns whatever the core produces.
5. **`chat.py` present()** — render `clarify[]` as the existing "HELP ME NARROW THIS DOWN" chips
   (screenshot 34 already does this for the post-retrieval case; now it also fires pre-retrieval).
6. **Frontend** — none required if the wire contract for `clarify` is unchanged; chips already exist.

**Telemetry:** stamp `decision.source = "clarify:pre_retrieval:<reason>"` so the census can separate
"asked one good question" from "guessed and got an empty" — the metric that proves the change.

---

## 6. Iterative TDD plan (red → green → refactor, maker/checker)

Each item is independently shippable and shadow-safe. Write the **red** test first; a **checker**
agent (separate from the maker) tries to refute the green before commit.

- **TDD-1 — empty-result clarify (R1/R5 inversion).**
  *Red:* `slot_gap_clarify(has_products=False, budget_known=False)` currently returns `None`; assert
  it returns an `ask_budget`/`widen` question. *Green:* flip the guard. *Checker:* prove it does not
  fire when `off_catalog` or a higher-priority clarify already claimed the slot.
- **TDD-2 — pre-retrieval clarify gate (§3.1/§5).** *Red:* an ambiguous bulk query with `budget_scope=None`
  routes to `SEARCH` and retrieves; assert it returns `status=clarify` with **zero** retrieval calls
  (spy on `retrieve`). *Green:* wire steps 1-3. *Checker:* prove a plain "show me laptops" (SEARCH,
  no required gap) still retrieves — no over-asking.
- **TDD-3 — confidence bands (§3.3).** *Red:* `confidence=0.3` on an ambiguous turn proceeds; assert
  it clarifies. `confidence=0.9` proceeds. *Green:* add the band check. *Checker:* the medium band
  hedges narration but still returns products (no silent empty).
- **TDD-4 — fallback→clarify (§3.4).** *Red:* model-unavailable + unrecognized category → assert
  `CLARIFY`, not empty `SEARCH`. *Green:* branch in `_bounded_fallback_decision`. *Checker:* a
  recognized sold category still fast-paths to the bounded search (no regression in the happy miss).
- **TDD-5 — kill the second router (§4).** *Red:* a characterization test pinning `chat` classification
  output for 20 queries; then route the same 20 through the core and assert parity. *Green:* delete
  the regex functions, delegate. *Checker:* diff must be empty on the frozen live battery.
- **TDD-6 — thin edge cutover (§4).** Shadow-diff `CHAT_EDGE_V2` wire output vs legacy on the golden
  set; promote only at 0 diffs.

**Guardrail metric per PR:** `empty_rate`, `clarify_rate`, `constraint_sat`, `p95`, `fallback_rate`
from the existing replay harness. A clarify change must **lower empty_rate without raising
over-ask** (a new `clarify_rate` ceiling, e.g. ≤ 15%).

---

## 7. Acceptable latency for UI/UX

**Principle:** optimize *perceived* latency (time-to-first-useful-paint), not p95. Established HCI
thresholds and the ShopSquire budget they imply:

| Threshold | HCI meaning | ShopSquire surface | Budget |
|---|---|---|---|
| ~100 ms | Feels instant | Clarify chips, cart add/remove, tab switch (Budget/Perf/All), filter re-sort | **≤ 100 ms** (all deterministic — no model) |
| ~400 ms (Doherty) | Keeps productive flow | First skeleton / "thinking" state, retrieved product cards (BOW retrieval is model-independent) | **≤ 400 ms to first paint** |
| ~1 s | Uninterrupted thought | Full ranked slate + fit banner | **≤ 1 s to products** |
| ~10 s | Attention limit; needs progress + escape | Narration / evidence / market-intel prose (the model leg) | **stream; never a blocking 7 s wall** |
| 200 ms–1.5 s | Voice turn-taking | Voice front-end (future) | **hard gate — blocks voice until met** |

**What this means concretely:**
- **The clarify path is your latency superpower.** It's template-only → ~instant. Every turn that
  clarifies instead of guessing is both more correct *and* faster. Fixing §3 improves both axes.
- **Retrieval is model-independent** (Postgres BOW, per the IMAGE-lane characterization) — you can
  paint product cards in <1 s **before** the router narration finishes. Decouple them (§8).
- **The 7 s wall is the narration/model leg.** Stream it; show products + a skeleton for prose. The
  user reads cards while tokens arrive. Perceived latency drops from 7 s to <1 s even with the same
  p95.
- **Voice is gated on the model leg**, not the retrieval leg. It cannot ship until `ROUTER_MODEL`
  latency work (warm-pin, preload, smaller model) lands — treat that as the voice precondition.

---

## 8. Pipeline reordering (cheap-first + progressive disclosure)

**Current order** puts the 7 s model call first, then everything waits on it. Reorder to run
deterministic, high-value work **before** and **in parallel with** the model:

1. **Cheap deterministic pre-pass (before the model):** shared gate, grammar-parse budget/quantity,
   obvious required-field gap → if the answer is "must clarify", **return the chip now** and never
   call the model. (This is §3.1 as a latency optimization.)
2. **Parallelize retrieve ∥ route** where the lane is obvious (a plain product noun): kick off BOW
   retrieval on the candidate nodes while the router runs, so cards are ready the instant the lane
   confirms `SEARCH`.
3. **Stream the response in layers:** (a) products + fit banner (<1 s) → (b) narration tokens
   (streamed) → (c) evidence/market-intel chips (lazy, on demand). The Decision Trace / Evidence tab
   already load on click — extend that laziness to prose.
4. **Move clarify detection to the front** of `recommend_turn`, not the last stage.

Net: same total compute, but the buyer sees something useful in <1 s instead of staring at a spinner
for 7 s.

---

## 9. Shopping experience / UI/UX improvements

Grounded in the two screenshots (chat + 3-band shelf + clarify chips + evidence chips + Decision
Trace):

- **Streaming narration + skeletons** (from §8) — the single biggest perceived-quality win.
- **One question, never an interrogation.** The doctrine is already "ask ONE bounded question"
  ([plan.py:17](../src/app/services/recommendation_core/plan.py#L17)). Enforce a **hard cap of one
  clarify chip-set per turn**, with a visible "or just show me anyway" escape (respects the 10 s /
  user-control HCI rule).
- **Make the 3-band shelf (Budget-fit / Performance-fit / All) the default mental model** — it's
  already built and it's genuinely good; lead with it instead of a flat list.
- **Progressive evidence disclosure** — chips collapsed by default, "why?" expands. Don't spend the
  narration budget on evidence the buyer didn't ask to see.
- **Honest-empty as a designed state, not a blank** — when retrieval is empty, the clarify-first gate
  turns a dead-end into "I didn't find X — widen budget, or source it from a supplier?" (ties to the
  procurement RFQ path — a *conversion* opportunity, not a failure).
- **Optimistic cart UX** — add/remove is deterministic; update the cart total instantly, reconcile
  server-side (the money-path idempotency work already protects this).

---

## 10. Roadmap — business + architectural trade-offs

| # | Item | Business value | Architectural cost / risk | Effort | Dep |
|---|---|---|---|---|---|
| 1 | **Empty-result clarify (TDD-1)** | Converts dead-end turns into guidance/RFQ; direct `empty_rate` ↓ | One branch; risk = over-ask (bounded by clarify-rate ceiling) | XS | none |
| 2 | **Pre-retrieval clarify gate (TDD-2)** | Fewer wrong/empty turns **and** faster (template-only) | New decision path; risk = asking when it should guess → cap + shadow | S | 1 |
| 3 | **Confidence bands (TDD-3)** | Graceful "not sure" instead of confident-wrong; trust | Uses existing field; low risk | S | 2 |
| 4 | **Fallback→clarify (TDD-4)** | Model-outage turns stay useful | Small; keep happy-miss fast path | S | 2 |
| 5 | **Delete chat regex router (TDD-5)** | Removes drift class; one source of truth | Characterization parity risk → frozen battery gates it | M | facade |
| 6 | **Thin chat edge + image_edge (TDD-6)** | Unblocks archive, MCP, voice; maintainability | Large surface; strangler-fig + shadow contains it | L | 5 |
| 7 | **Stream + progressive disclosure (§8/§9)** | 7 s→<1 s *perceived*; conversion & satisfaction | Frontend streaming contract + backend token stream | M | none |
| 8 | **Router latency (warm-pin/preload/smaller model)** | Real p95 ↓; **voice precondition** | Ops + model-choice; measured, low code risk | M | none |
| 9 | **Voice front-end** | New modality; procurement-by-voice (draft-only) | Thin *iff* core is clean+fast; STT/TTS integration | L | 6,8 |
| 10 | **MCP inbound (facade)** | Agent-native commerce; governance = moat | New protocol surface; auth/authz on tools | L | 6 |
| 11 | **Temporal hippograph (recency-weight → invalidation)** | Retires stale-constraint bug class; market-intel trust | Evolve existing recall; shadow-first | M | none |

**Sequencing:** 1→2→3→4 are a single low-risk sprint that moves stuck metrics *now* with no
dependency on the archive. 5→6 is the archive-critical refactor. 7+8 are parallel perceived-latency
tracks (7 needs no model work; 8 is the voice gate). 9/10/11 are the strategic payoff **after** the
edge is thin — building them before 6 means building on the monolith, which the doctrine forbids.

---

## 11. What this does *not* change

- The **human-only-send invariant** for procurement is untouched (voice/MCP draft, never send).
- The **agnostic core** doctrine is reinforced (deleting the chat regex router removes an
  electronics-flavoured decision surface from the edge).
- The **off→shadow→canary** governance ladder is the delivery mechanism for every item above —
  nothing here ships without a shadow diff and a promotion metric.
