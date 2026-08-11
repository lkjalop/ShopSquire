# Cart / Explain / Amend — Defect Assessment, Narration Contract, UX Wireframes

**Date:** 2026-08-08 · **HEAD:** `4d6bf7c0` · **Scope:** screenshots 51, 52, 53 — assessment only, no code changed
**Companion:** [SHOPSQUIRE_DELTA_RETEST_2026-08-08.md](SHOPSQUIRE_DELTA_RETEST_2026-08-08.md)

---

## 1. What the three screenshots actually show

All three are the same turn shape — **one utterance carrying three acts**:

```
"why is <SKU> a good choice?"   →  EXPLAIN      (read-only, needs fit ledger)
"can you add 30 more?"          →  AMEND_QTY    (mutation, needs confirm)
"i need it in 4 days?"          →  CONSTRAIN    (deadline, needs fulfilment evidence)
```

They differ only in how well the system handled that shape.

| | 51 | 52 | 53 |
|---|---|---|---|
| EXPLAIN | ❌ silently dropped, replaced by a budget question | ⚠️ **honestly refused** | ⚠️ honestly refused |
| AMEND_QTY | ❌ never applied, qty stayed 30 | ✅ correctly read as 30→**60** | ❌ proposed, never applied |
| CONSTRAIN (4 days) | ❌ ignored | ✅ honestly refused with reasons | ✅ honestly refused |
| Compound (add + clear) | — | — | ❌ only one act proposed, neither applied |

**Screenshot 52 is the best behaviour in the set and should be the baseline**, not the bug report.
It says: *"I can propose the quantity change, but the accepted workload-fit ledger for this exact
SKU is unavailable, so I will not invent a capability explanation."* That is the honesty layer
working exactly as designed. The defect is that the ledger is empty — not that it declined.

**Screenshot 51 is the dangerous one.** It answers an EXPLAIN request with
*"I didn't find a match yet — what budget range should I stay within so I can look again?"*
while the cart holds 30 units of that very product at $179,970. The statement is false, and it
converts a lost explanation into an apparently-unrelated interrogation.

---

## 2. Defect list

### D1 — Fit ledger not populated for the selected SKU 🔴 root cause

Explanation is looked up from session, keyed by SKU:

- [`cart_compound_response.py:62-70`](../src/app/services/recommendation_core/cart_compound_response.py#L62) — `session["last_product_explanation"]`, falling back to `session["product_explanations"][sku]`
- [`core.py:2502-2517`](../src/app/services/recommendation_core/core.py#L2502) — `product_explanations[str(card.sku)] = card_payload`, written into `resp.extras`
- [`cart_session_state.py:28-29`](../src/app/services/cart_session_state.py#L28) — both keys are in the persisted allowlist

So the wiring exists end to end and still returns `accepted_fit_evidence_unavailable`
([`cart_compound_response.py:94-102`](../src/app/services/recommendation_core/cart_compound_response.py#L94)). The SKU the buyer carted is not among the SKUs whose
explanation was written, **or** the extras→session persistence does not run on the cart-mutation
short-circuit path (which returns early at [`recommendation_facade.py:436-447`](../src/app/services/recommendation_facade.py#L436) and may never reach the
persistence step).

**What to do:** trace one turn and assert `session["product_explanations"].keys()` contains the
carted SKU immediately after the add. If the keys are present but the SKU differs, it is a SKU
identity mismatch (card SKU vs cart line SKU). If the dict is empty, the cart short-circuit is
bypassing persistence. Same defect as the turn-4 context loss in the delta retest — one fix, two
symptoms.

### D2 — EXPLAIN intent is lost when the turn also mutates 🔴

In 51 the EXPLAIN act never reached [`cart_compound_response.py`](../src/app/services/recommendation_core/cart_compound_response.py) at all; the turn fell through to
retrieval, found nothing, and hit the empty-slot clarifier. `wants_explanation` is computed at
[`cart_compound_response.py:72-76`](../src/app/services/recommendation_core/cart_compound_response.py#L72) from `intent_hint == "EXPLAIN"` or `is_followup_explain_query(query)`.
A three-act utterance is apparently classified by its *mutation* act, so the explain act is
discarded rather than answered alongside.

**What to do:** intents in one utterance must be a set, not a winner. `decompose_case_obligations`
([`cart_compound_response.py:105-115`](../src/app/services/recommendation_core/cart_compound_response.py#L105)) already returns multiple obligation kinds — the response
composer should be obliged to emit one narration block per obligation, and to record a block as
`unanswered` rather than dropping it.

### D3 — Clarifier contradicts known state 🔴

[`gates.py:41-48`](../src/app/services/recommendation_core/gates.py#L41) `slot_gap_clarify(has_products=False, budget_known=False)` →
*"I didn't find a match yet — what budget range should I stay within so I can look again?"*

`has_products` refers to **this turn's retrieval**, but the buyer has a selected, carted product.
The message asserts "no match" as a fact about the conversation. It is also the "redundant budget
question" from screenshot 49.

**What to do:** gate this clarifier on cart/selection emptiness too, not only on retrieval
emptiness. A turn with a non-empty cart can never honestly say "I didn't find a match yet". Add
`has_selection` / `cart_non_empty` to the signature and return `None` when either is true.

### D4 — Quantity arithmetic is correct; routing to it is not ⚠️

The arithmetic is right — do **not** change it:

- [`cart_resolver.py:153-161`](../src/app/services/recommendation_core/cart_resolver.py#L153) — matches `add|increase|raise … N` and `N more`, returns `("add", N)`
- [`cart_resolver.py:665-666`](../src/app/services/recommendation_core/cart_resolver.py#L665) — `mode == "add"` → `qty = current_qty + operand`
- [`cart_resolver.py:684`](../src/app/services/recommendation_core/cart_resolver.py#L684) — emits `set_quantity` with `previous_quantity` and `allow_sourcing`

Screenshot 52 proves it: 30 + 30 → *"change a line to 60 unit(s)"*. Screenshot 51's "should be
60???" is **not** an arithmetic bug — that turn never reached the resolver (D2). Screenshot 53's
is a confirm/apply bug (D5).

### D5 — Pending mutation plan is silently discarded by the next message 🔴

- [`recommendation_facade.py:436-447`](../src/app/services/recommendation_facade.py#L436) — confirmation-only by default; returns
  `cart_mutation.needs_confirmation = true` with a `plan_id` and `expires_at`, `cart_updated: false`
- Applying requires `POST /cart/mutations/{plan_id}/apply`
- [`recommendation_facade.py:415-419`](../src/app/services/recommendation_facade.py#L415) — plans below `_MIN_EXEC_CONFIDENCE` fall through with no user-visible trace

In 53 the buyer typed a new message instead of clicking confirm. That created a second plan; the
first was abandoned. Nothing applied, and the identical confirm sentence was emitted twice, which
reads as a hang.

The confirmation-only default is **correct** (comment at [`recommendation_facade.py:436`](../src/app/services/recommendation_facade.py#L436) explains
why: a model false positive must not mutate a cart). The defect is purely surfacing: the pending
plan has no persistent, visible affordance, and superseding it is silent.

**What to do:** render pending plans as a durable card bound to `plan_id` with its `expires_at`,
and when a new plan supersedes an unconfirmed one, say so explicitly.

### D6 — Compound cart commands collapse to one act 🔴

53's input was two commands: *"add 30 for ASUS ProArt … clear 30 Lenovo Legion Pro 7 …"*. Only the
quantity change was proposed; the clear was not mentioned at all. The ops vocabulary
([`cart_resolver.py:52-55`](../src/app/services/recommendation_core/cart_resolver.py#L52)) supports `clear_all | clear_previous | remove_items | set_quantity |
keep_only | replace_item` and the prompt at [`cart_resolver.py:426`](../src/app/services/recommendation_core/cart_resolver.py#L426) explicitly contemplates
emitting *"a remove_items op AND a set_quantity op"* — so multi-op plans are representable.

**What to do:** determine whether the model emitted one op or two and the second was dropped
downstream. Then make the confirm card enumerate **every** op in the plan, so a dropped op is
visible instead of silent.

### D7 — Deadline is answered honestly but not actionably ⚠️

52/53: *"I cannot confirm 60 units within 4 days from stock counts alone; dated local arrival,
transfer ETA, and any supplier-confirmed arrival still need verification."*

Correct and well-grounded — but the buyer is left with no move. There is no "request a dated
commitment" action, no operator hand-off, no partial-now/rest-later proposal, even though the
delivery-plan panel already knows 7 local + 23 transfer and
`supplier_enquiry_option` exists at [`core.py:1195`](../src/app/services/recommendation_core/core.py#L1195).

### D8 — No commercial gap reasoning ⚠️

Nothing proposes cheaper / more capable / fewer units / substitute / supplier-sourced when the
floor, budget, quantity, or date cannot all be met. `align_catalog` already produces an
`alternatives` bucket ([`core.py:1174`](../src/app/services/recommendation_core/core.py#L1174), filtered at [`core.py:1194`](../src/app/services/recommendation_core/core.py#L1194)) that is never narrated as a
trade-off.

### D9 — Guest token budget blocks the journey 🔴 (from the delta retest)

`.env:27` `TOKEN_BUDGET_GUEST_DAILY_TOKENS=1000` vs code default and `.env.example:48` = `10000`;
~505 tokens/turn ⇒ one turn per guest per day. [`token_budget.py:56-62`](../src/app/services/token_budget.py#L56).

### D10 — Concept discovery unenrolled ⚠️

[`research_provider_registry.py:151`](../src/app/services/research_provider_registry.py#L151) requires `EXTERNAL_RESEARCH_SEARCH_URL`; trace shows
*"No configured provider: not configured for concept discovery"* and
*"web: research pending — Provider status: cost budget exceeded"*.

---

## 3. Narration contract — what the LLM should say

Derived from the intent in 52/53. **One block per act. Every act gets a block, including
unanswerable ones. No act may be silently replaced by a question about a different act.**

### Slot structure

```
[1] FIT VERDICT      — the EXPLAIN act
    workload         : the retained buyer purpose, quoted back
    floor            : each compiled predicate, observed vs required, per-attribute verdict
    verdict          : meets | partially meets | does not meet | UNVERIFIED
    evidence         : provider + freshness + claim id
    if UNVERIFIED    : say so, then give the RECOVERY MOVE
                       ("name the workload" / "authorize a source check")
                       -- never a budget question

[2] COMMERCIAL DELTA — the AMEND_QTY act
    change           : SKU, current -> proposed (explicit arithmetic: 30 + 30 = 60)
    price            : unit x qty = line total, and the delta from now
    budget           : impact on stated budget, headroom or overrun
    affordance       : one confirm control bound to plan_id, with expiry
    supersession     : if this replaces an unconfirmed plan, say which

[3] FULFILMENT TRUTH — the CONSTRAIN act
    known            : n local now / n transfer / n supplier, with source
    unknown          : what evidence is missing (dated arrival, transfer ETA)
    owner            : who must verify (fulfilment operator)
    moves            : request dated commitment | split partial-now | reduce qty | substitute

[4] TRADE-OFF        — only when a constraint cannot be met
    "this floor at this quantity by this date costs $X and cannot be confirmed.
     Options: raise budget to $Y | reduce to N units by <date> | qualified
     substitute <SKU> at $Z | draft supplier RFQ (human review)"
```

### Rules

1. **Never assert a state contradicted by the cart.** "I didn't find a match yet" is prohibited
   whenever a selection or cart line exists. (D3)
2. **An unanswerable act is answered, not swapped.** 52's refusal sentence is the model to follow;
   51's budget question is the anti-pattern.
3. **Every clarifying question must discriminate.** If the answer cannot change the surviving
   candidate set or unblock the act, do not ask it. Budget after a $179,970 cart is not
   discriminating.
4. **Arithmetic is shown, not implied.** "30 + 30 = 60", "$4,894 × 30 = $146,820".
5. **Evidence status is per-claim**, not per-message. Fit may be UNVERIFIED while fulfilment is
   partially known, in the same turn.
6. **Deadlines are never promised** — state known, unknown, owner, and moves. (52 already does the
   first three; add the fourth.)

---

## 4. UX wireframes — three options

### Option A — Inline Fit Receipt (smallest change)

Everything stays in the chat stream; the fit ledger becomes a structured block.

```
+-- ShopSquire Assistant --------------------------------+
|                                                        |
|  [you] why is Lenovo Legion Pro 7 a good choice?       |
|        can you add 30 more? i need it in 4 days?       |
|                                                        |
|  +--------------------------------------------------+  |
|  | FIT — Lenovo Legion Pro 7 16IAX10H               |  |
|  | for "digital twin / machine breakdown"           |  |
|  |--------------------------------------------------|  |
|  | RAM        64 GB   >= 32 GB required     [MEETS] |  |
|  | GPU VRAM   16 GB   >=  8 GB required     [MEETS] |  |
|  | Virtualise  not recorded                 [UNKN.] |  |
|  |--------------------------------------------------|  |
|  | Verdict: MEETS 2 of 3 accepted requirements      |  |
|  | Source: official requirements api - 2026.08      |  |
|  +--------------------------------------------------+  |
|                                                        |
|  +--------------------------------------------------+  |
|  | QUANTITY — proposed, not applied                 |  |
|  | 30 + 30 = 60 units                               |  |
|  | $5,999 x 60 = $359,940  (+$179,970)              |  |
|  |            [ Confirm 60 ]  [ Keep 30 ]           |  |
|  | expires 14:32                                    |  |
|  +--------------------------------------------------+  |
|                                                        |
|  +--------------------------------------------------+  |
|  | 4-DAY DEADLINE — cannot confirm                  |  |
|  | known    7 local now, 23 network transfer        |  |
|  | missing  dated arrival, transfer ETA             |  |
|  | owner    fulfilment operator                     |  |
|  | [Request dated commitment] [Ship 7 now, rest later]|
|  +--------------------------------------------------+  |
+--------------------------------------------------------+
```

*Pros:* no new surface, reads as conversation, each act visibly answered.
*Cons:* long stream; the fit receipt scrolls away and must be re-asked.

---

### Option B — Persistent Fit Panel (recommended)

Chat stays prose. The right panel gains a **Fit** tab beside Cart, so the ledger persists across
turns — which is also the structural answer to "multi-turn is not going back to first reason why".

```
+-- Assistant ------------+  +-- [Fit] [Cart] [Delivery] -----------+
|                         |  |                                      |
| [you] why is this a     |  | RETAINED PURPOSE                     |
| good choice? add 30     |  | "digital twin project /              |
| more? need it in 4 days?|  |  machine breakdown"          [edit]  |
|                         |  |                                      |
| Fit: meets 2 of 3       |  | ACCEPTED FLOOR      src: official     |
| accepted requirements   |  |   RAM        >= 32 GB    2026.08     |
| — see Fit tab. One      |  |   GPU VRAM   >=  8 GB    2026.08     |
| requirement is          |  |   Virtualise  not established        |
| unverified.             |  |                                      |
|                         |  | SELECTED                             |
| Quantity: proposed      |  |  Lenovo Legion Pro 7   $5,999        |
| 30 -> 60. Confirm in    |  |   RAM       64 GB   [MEETS]          |
| the Cart tab.           |  |   GPU VRAM  16 GB   [MEETS]          |
|                         |  |   Virtualise  --    [UNVERIFIED]     |
| 4 days: I cannot        |  |                                      |
| confirm. 7 local, 23    |  | ALTERNATIVES vs this floor           |
| transfer; dated arrival |  |  ASUS ProArt 16    $4,894  [MEETS]   |
| unverified. A           |  |     -$1,105/unit, -$33,150 at 30     |
| fulfilment operator     |  |  Alienware 16      $3,499  [FAILS]   |
| must verify.            |  |     RAM 16 GB < 32 GB required       |
|                         |  |                                      |
+-------------------------+  +--------------------------------------+
```

*Pros:* the floor and verdict survive every turn; alternatives become a real trade-off surface
(closes D8); "why" is always one click away, so the explain act can never be lost.
*Cons:* new panel + state to maintain.

---

### Option C — Decision Card with act-tabs (most explicit)

One card per turn, one tab per act, each tab carrying its own evidence badge.

```
+-- This turn: 3 requests --------------------------------+
| [ Fit ! ]  [ Quantity * ]  [ Delivery ! ]               |
|  ! unverified   * awaiting confirm                      |
+---------------------------------------------------------+
| FIT                                                     |
|   Lenovo Legion Pro 7  for  digital twin / machine      |
|   breakdown                                             |
|                                                         |
|   MEETS      RAM 64 GB          >= 32 GB                |
|   MEETS      GPU VRAM 16 GB     >=  8 GB                |
|   UNVERIFIED nested virtualisation — not in the         |
|              accepted ledger for this SKU               |
|                                                         |
|   I will not claim this is qualified for the            |
|   virtualisation part without evidence.                 |
|                                                         |
|   [Check approved sources]  [Tell me the workload]      |
+---------------------------------------------------------+
```

*Pros:* every act's status is legible at a glance; unanswered acts are impossible to hide — makes
D2 structurally unrepresentable.
*Cons:* heaviest build; tabbed UI inside a chat can feel bureaucratic for simple turns.

---

### Cart confirm surface (applies to all three options)

Fixes D5/D6 — the pending plan must be durable, enumerate every op, and announce supersession.

```
+-- PENDING CART CHANGE — nothing applied yet ------------+
|  plan 7f3a  ·  expires in 4:12                          |
|                                                         |
|   1. ASUS ProArt 16      30 -> 60   (+30)   +$146,820   |
|   2. Lenovo Legion Pro 7 30 ->  0   (clear) -$179,970   |
|                                                         |
|   Net: $326,790 -> $293,640                             |
|                                                         |
|   [ Apply both ]  [ Apply 1 only ]  [ Discard ]         |
|                                                         |
|  ! Typing a new request replaces this pending change.   |
+---------------------------------------------------------+
```

---

## 5. Recommendation

**Option B.** It is the only one that also fixes the underlying problem rather than presenting it
better: a persistent Fit panel forces the retained purpose and accepted floor to be first-class
session state, which is exactly what D1 and the turn-4 context loss both need. Options A and C can
be layered on later; the confirm-surface wireframe should ship regardless.

---

## 6. Fix order

| # | Defect | Where | Why first |
|---|---|---|---|
| 1 | D1 fit ledger not persisted/matched | [cart_compound_response.py:62](../src/app/services/recommendation_core/cart_compound_response.py#L62), [core.py:2502](../src/app/services/recommendation_core/core.py#L2502), [cart_session_state.py:28](../src/app/services/cart_session_state.py#L28) | every explanation defect is downstream |
| 2 | D9 guest budget | `.env:27` → `10000` | one line; nothing is demonstrable without it |
| 3 | D3 contradictory clarifier | [gates.py:41-48](../src/app/services/recommendation_core/gates.py#L41) | it states a falsehood; cheapest honesty win |
| 4 | D2 multi-act intent | [cart_compound_response.py:72](../src/app/services/recommendation_core/cart_compound_response.py#L72), obligations at `:105` | stops acts being dropped |
| 5 | D5/D6 pending plan surface | [recommendation_facade.py:436](../src/app/services/recommendation_facade.py#L436) + frontend | UI-led; resolver arithmetic is already correct |
| 6 | D7/D8 moves + trade-offs | [core.py:1174](../src/app/services/recommendation_core/core.py#L1174)/[:1195](../src/app/services/recommendation_core/core.py#L1195) | needs 1 and 4 first |
| 7 | D10 concept discovery | [research_provider_registry.py:151](../src/app/services/research_provider_registry.py#L151) | config + provider |

**Do not touch** [`cart_resolver.py:665`](../src/app/services/recommendation_core/cart_resolver.py#L665) — the additive arithmetic is correct and screenshot 52 proves it.
