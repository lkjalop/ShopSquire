# ShopSquire — Pilot Readiness, Procurement Cycle & Autonomy Assessment

**Date:** 2026-09-09 · **HEAD:** `eb78d908` · **Working tree:** 20 modified / 8 untracked
**Window assessed:** 2026-09-07 → 2026-09-09 (7 commits, +309/−54) plus the uncommitted
evidence-compiler work (+474/−25)
**Prior:** `SHOPSQUIRE_DELTA_REASSESSMENT_2026-09-07.md`,
`SHOPSQUIRE_GODFUNCTION_AND_DETERMINISM_SURVEY_2026-09-07.md`

Every claim below is independently re-derived — AST analysis, offline execution of the real
functions, the live HTTP surface, and full test runs. Repair receipts were read for orientation
only, never used as evidence.

---

## 0. Executive verdict

**Two days of small, high-quality commits.** All three findings I raised on 09-07 are closed,
verified by execution. `chat.py` **shrank for the first time in the arc** (5,823 → 5,787).

**The important thing that happened is counter-intuitive: the platform got more correct and
less capable at the same time.** The evidence compiler now refuses to treat a desktop→laptop
GPU translation as a publisher claim, so PRAGMATA's requirement coverage is honestly `partial`,
so the catalog gate honestly stays `blocked`, so the buyer still sees no shelf. The team's own
note on this is the right instinct: *"do not relax the authority gate to manufacture a qualified
shelf."*

**Pilot readiness: the procurement spine is the strongest part of the platform and is close.
The buyer-facing recommendation path is not.** Those two conclusions are independent, and that
matters for how you pilot.

| Track | Grade | One-line reason |
|---|---|---|
| Procurement / RFQ cycle | **B+ — pilot-ready with 3 named gaps** | 55-transition FSM, 372 tests green, fail-closed autonomy |
| Money & idempotency | **B** | Ledger + attempts + reconcile + idempotency keys; Postgres row locks conditional |
| Security & tenancy | **B+** | 142 security test files, 380 touching tenancy, `/readyz` clean |
| Buyer recommendation delivery | **D — blocked** | Positive shelf gate has never gone green live |
| Architecture debt | **C+ — improving** | 3 size breaches (was 6); ratchets otherwise green |
| Autonomy readiness | **B for propose, A for refuse, D for act** | Correct by construction; needs SoD before widening |

---

## 1. What moved since 09-07

### 1.1 All three of my findings — closed, verified by execution

| Finding (09-07) | Status | Evidence |
|---|---|---|
| `chat.py:321` legacy budget fallback overrode canonical refusals | ✅ **Deleted** | `"1500 to 2000 employees"` → canonical `None`, chat `{None, None}`. Previously invented 1500–2000 |
| The "computer chair" scope defect (`related` used as a filter before ranking) | ✅ **Fixed** | Now `status=out_of_category`, node `fr-7 Furniture > Chairs`, with **and** without a client handle. Fixed via head-noun preservation, not a chair-name exception |
| `write_feature_flags` wrote to the tracked `config/feature_flags.json` | ✅ **Fixed** | Now **raises `ValueError`** if the path is unset or resolves to the tracked config; pytest collection uses a disposable file; 5 modules snapshot/restore |

The chair case is worth dwelling on, because it validates the method. My deterministic
reproduction was one of **two** independent causes. The second only appeared under the live
model: the router returned valid JSON with an out-of-vocabulary lane → `fallback:invalid_lane`.
The fix was to constrain `lane` to the existing `LANES` enum via a **structured-output schema** —
not a lane alias table. Both causes had to be fixed before the live test passed. It now does.

### 1.2 The evidence compiler was rebuilt to refuse

Three checkpoints (`COMPILER_BOUNDARY_REPAIR`, `MANIFEST_SCOPE_CHECKPOINT`,
`LITERAL_EVIDENCE_CHECKPOINT`) plus a new `requirement_scope.py`:

- **Units and operators validated.** A RAM claim in `mg` is rejected, not relabelled GB.
  Numeric `contains` is rejected. Non-finite values rejected.
- **Scope is pinned, not unioned.** `RequirementScope` (frozen: tenant, product type,
  relationship, manifest id, 64-char content revision) replaces "union every installed
  vertical". Cross-category attributes are explicitly rejected. **Provider claims do not select
  the manifest** — the server does.
- **Derived ≠ observed.** The GPU comparison-table threshold is tagged derived and rejected for
  authoritative compilation (`derived_claim_requires_policy`). The publisher excerpt survives in
  the rejection receipt. **No replacement literal GPU parser was invented.**
- **Literal observations preserved.** CPU/GPU/OS source-line receipts with bounded spans;
  bounding validates that the cited substring *exactly equals* the retained value, so forged or
  normalisation-mismatched spans are dropped rather than manufactured. They stay `observed` with
  `fit_authority: none`.
- Approved tenant documents are no longer auto-marked publisher-verified.

This is the single most principled piece of work in the arc. It is also why delivery is still
blocked — see §4.

### 1.3 Live browser gate: 3 of 4

| Scenario | Result |
|---|---|
| Computer chair → off-catalog refusal | ✅ passes (was failing) |
| Unrelated question | ✅ passes |
| Bulk stock accounting | ✅ passes |
| **PRAGMATA positive delivery** | ❌ **fails** — identity and narration correct, two claims accepted, but `attribute_not_registry_authorized` rejection and **partial** coverage → catalog stays blocked |

---

## 2. Current health, measured

| Suite | Result |
|---|---|
| `tests/services` + `tests/integration` + `tests/architecture` | **3 failures** |
| — `test_ranking_nudge_wiring` ×2 | real capability gap — see §2.1 |
| — `test_source_file_size_guard` | the 3 known breaches |
| **Procurement suite** (43 files) | **372 tests, 0 failures** |
| Exception-swallowing ratchet | ✅ green |
| Async/sync-session boundary | ✅ green |
| Alembic | single head, no divergent branches |
| `/readyz` secret scan | clean (7 allowlisted fields) |

Size guard: `chat.py` **5,787** (ceiling 5,049) · `fulfillment_cases.py` 2,574 (2,447) ·
`shopping_cases.py` 2,397 (2,073). Three breaches, down from six on 09-04.

### 2.1 New finding: the ranking-nudge experiment never reaches buyer traffic

`test_ranking_nudge_wiring` fails **in isolation**, not just in a sweep — so it is not the old
flag-pollution class. The cause:

```
ranking_nudge references:  config.py · fulfillment_cases.py · experiment_console.py
                           services/recommend_intelligence_stage.py   ← legacy V1 stage
recommendation_core/*:     zero references
```

With `RECOMMEND_CORE_MODE=primary`, the experiment is wired to a stage the buyer path no longer
executes. This is a **capability silently lost in the V2 cutover**, and the test is correctly
red about it. Either re-wire it into the core or retire the experiment and its tests — but do
not leave a shipped experiment console pointing at a dead lever.

---

## 3. End-to-end procurement cycle — the shortfall → supplier draft question

This is the strongest subsystem in the platform, and it is worth being precise about what is
proven and what is not.

### 3.1 The path, as built

```
buyer asks for N units
   │
   ▼  chat → recommendation core → shelf (catalog is 50 configs, stock 5–14)
add to cart at qty N
   │
   ▼  sourcing preview: shortfall = N − available
SourcingIntentCard  ──►  POST /api/v1/fulfillment/cases/confirm-cart
   │                     • buyer principal resolved, rate-limited per buyer
   │                     • ship_to validated — an unshippable address is REJECTED here
   │                     • lines resolved to SKUs
   │                     • CURRENT stock re-read at confirm time (not preview time)
   │                     • combined_availability(): local ATP · network transferable ·
   │                       supplier_rfq_qty  ← the true shortfall
   │                     • buyer's confirmed qty recorded as an OVERRIDE with authority +
   │                       reason, never silently substituted
   │                     • idempotent on order_id — a double submit returns the SAME cases
   ▼
one durable case per supplier group, each parked at GATE 1
   │
   ▼  availability_assessed            [AGENT,  requires evidence]
   ▼  request_buyer_commitment         [AGENT/SYSTEM]
   ▼  buyer_committed                  [BUYER]        ◄── GATE 1
   ▼  supplier_candidates_ranked       [AGENT,  requires evidence]
   ▼  external_message_drafted         [AGENT,  CONFIDENCE-GATED + evidence]
   ▼  approval_requested               [AGENT]
   ▼  approval_granted                 [HUMAN_OPERATOR]
   ▼  external_message_sent            [HUMAN_OPERATOR]  ◄── GATE 2
   ▼  external_message_received        [EXTERNAL/SYSTEM]
   ▼  supplier_response_parsed         [AGENT]
   ▼  supplier_quote_validated         [HUMAN_OPERATOR]
   ▼  fulfillment_options_generated    [AGENT,  CONFIDENCE-GATED]
   ▼  buyer_fulfillment_selected       [BUYER]
   ▼  purchase_order_proposed          [AGENT]
   ▼  purchase_order_approved          [HUMAN_OPERATOR]  ◄── GATE 3 window opens
   ▼  purchase_order_created → goods_receipt → invoice → completed
```

**55 transitions.** Actor reach: human_operator 33 · system 26 · agent 18 · buyer 12 ·
external 3. **9 agent-only** transitions (all propose/assess/parse/draft). **14 human-only**
(qualify, RFI, approve, send, validate quote, approve PO, supersede after send, cancel).

### 3.2 The draft cage

`services/fulfillment/draft.py` — the agent may draft freely; the cage guarantees:

1. **Recipient comes from the trusted-supplier allowlist and the ranked approved set, never
   from buyer text.** A prompt-injected "email attacker@evil.com" cannot redirect the message.
2. **No price, no commitment language** — a claim-safety guard rejects leakage. The supplier is
   *asked* to quote.
3. **Mandatory "this is not a purchase order" footer.**
4. **Discrete evidence IDs + plain-English rationale** — supplier reliability, market urgency,
   inventory shortfall, external benchmark.
5. **`content_hash` pins the message** — an edit changes the hash and voids the prior approval.
6. **Buyer view is redacted** (`_BUYER_REDACT = draft, inbound, quarantine`); the buyer sees
   `drafted: true`, `status: human_gated_not_sent`, gate decision and hash — never the body,
   never wholesale cost.

### 3.3 What is confirmed, and what is not

**Confirmed (offline, 372 tests, 0 failures):** the FSM actor guards; idempotent case
materialisation; shortfall arithmetic including multi-location transfer; draft claim-safety;
recipient allowlisting; content-hash invalidation; approval tiers; autonomous-send escalation
and audit; PO idempotency and out-of-scope quantity refusal; buyer-view redaction; cross-tenant
case hiding; RFQ fan-out shape; change-order and cancellation paths; quote expiry and parse
failure; supplier-response quarantine.

**Confirmed live (browser, zero retries):** bulk stock accounting — the buyer-visible
economics (`quantity`, `total_budget_cents`, `budget_shortfall_cents`) reconcile exactly against
the inventory snapshot (`local_atp`, `transferable`, `unconfirmed_shortfall`), with degraded /
unknown freshness preserved rather than papered over.

**Not yet confirmed — the three gaps that matter for a pilot:**

1. **No live end-to-end run from cart-confirm through to an operator reading the draft.** The
   pieces are individually tested; the seam has never been exercised in one browser session.
2. **No live supplier-dispatch-absence certificate.** The tests prove the agent *escalates*;
   nothing yet proves that during a full live journey, zero outbound messages left the box.
3. **Budget shortfall and stock shortfall have never been exercised independently.** They are
   different refusals with different buyer copy, and today only the combined case is covered.

---

## 4. Why the buyer shelf is still empty (and why that is not a bug)

The PRAGMATA live failure decomposes cleanly:

- Identity resolution: ✅ correct, cited, narrated with the canonical title.
- Steam evidence: ✅ retrieved, two claims compiled and **accepted**.
- One claim rejected: `attribute_not_registry_authorized`.
- GPU minimum: derived through **desktop→laptop VRAM translation** — a *derivation*, not a
  publisher claim, and the compiler now correctly refuses to treat it as authoritative.
- ⇒ coverage `partial` ⇒ `catalog_authority: blocked` ⇒ empty shelf, with honest narration.

**The gate is behaving exactly as designed.** The missing piece is not the gate; it is a
**governed derivation ledger**: versioned derivation rules, an approval provenance record, and
an accepted/observed/derived tri-state so a *reviewed* translation can carry authority while an
ad-hoc one cannot. Until that exists, any GPU-constrained workload will stay partial.

That is the single highest-value item on the roadmap, and it should not be short-circuited by
relaxing the authority gate.

---

## 5. Pilot production readiness, dimension by dimension

| Dimension | Grade | Evidence | Gap for pilot |
|---|---|---|---|
| **Procurement FSM** | A− | 55 typed transitions, actor guards, 372 tests green | Live seam test |
| **Autonomy safety** | A | Default OFF, 9 stacked guards, fail-closed to escalate | — |
| **Draft cage** | A− | Allowlist recipient, claim-safety, hash, redaction | Live injection test |
| **Money path** | B | ledger · attempts · reconcile scheduler · webhook delivery · idempotency keys across 12+ routers | Row locks are Postgres-conditional; needs a real-PG concurrency run |
| **Tenancy** | B+ | 380 test files touch tenancy; cross-tenant case hiding tested | Not certified on shared PG |
| **Secrets** | B+ | `/readyz` verified clean live, 7 allowlisted fields | Rotation policy undocumented |
| **Migrations** | A− | 137 migrations, **single head** | Never run forward on clean PG in CI |
| **Observability** | B | Decision log ON by default even in prod, bitemporal trace, 15 trace panels | Trace panels not reconciled to terminal truth |
| **Separation of duties** | **D** | Identity captured as an audit axis only | **See §6.2 — the top pilot blocker** |
| **Buyer delivery** | D | Positive shelf gate never green live | §4 |
| **Architecture** | C+ | 3 breaches (was 6); other ratchets green | `chat.py` 5,787 |
| **Clean-machine cert** | **F — not attempted** | Clean *checkout* passes 70 focused tests, same interpreter | No clean machine, no PostgreSQL, no hosted run |

### 5.1 The honest summary

For a **pilot with a friendly customer, on this machine or one like it, with an operator in the
loop**, the procurement cycle is close: fix the three §3.3 gaps and add SoD.

For **production-grade** — a real store, real money, shared infrastructure — the blockers are
clean-PostgreSQL certification, a concurrency run on real row locks, and independent source
review. None of those has been attempted, and the team says so plainly.

---

## 6. Autonomy: what is safe now, what must stay gated

### 6.1 The design is correct by construction

The split is textbook propose/dispose, and it is enforced in a pure module with no I/O
(`domain.py`), so every downstream layer inherits it rather than re-implementing it.

**Safe to run autonomously today** (already agent-only, evidence-required):

- Availability assessment and shortfall computation
- Supplier candidate ranking
- RFQ drafting (confidence-gated, caged)
- Requesting human approval
- Parsing supplier responses
- Generating fulfilment options (confidence-gated)
- Proposing a purchase order

**Must remain human — and currently is:**

- Buyer qualification / disqualification
- Supplier RFI
- Approval grant / rejection
- **External send** (GATE 2)
- Supplier quote validation
- **Purchase-order approval** (GATE 3)
- Order cancellation, and supersede after a send

**The one autonomy escape hatch, and its guards.** `approval_granted_autonomous` and
`external_message_sent_autonomous` exist as distinct AGENT-fired events, so the human-only
invariant is untouched and the trace records that the send was autonomous. Enabling them
requires **all nine** guards:

```
flag ON ∧ not killed ∧ recipient trusted (allowlist + KYV, risk ≤ medium)
∧ draft claim-safe ∧ draft complete ∧ confidence ≥ 0.8
∧ value ≤ $5,000 ∧ quantity ≤ 25 ∧ under 10/hour
∧ adaptive_action_gate authorizes
```

Any failure escalates to the human gate; the function never raises and never changes state on
escalate. Kill switches are honoured from three independent sources. Default: **OFF**, and the
live runtime reports `supplier_autonomy: off`.

**One asymmetry worth noting:** `approval_granted_autonomous` carries
`requires_confidence_gate=True`, but `external_message_sent_autonomous` does not. The confidence
gate sits on the approval, not the send. In practice `maybe_autonomous_send` evaluates both
together, so there is no live hole — but the FSM row does not encode it, and a future caller
firing the send event directly would bypass the gate. Worth tightening before autonomy is ever
switched on.

### 6.2 The gap that blocks widening autonomy: separation of duties

Measured:

- `Actor` carries an optional `user_id` (JWT sub) as an **audit axis**, stamped into the trace.
- Approval tiers exist (`auto` ≤ $1k → `manager` ≤ $10k → `director` ≤ $100k → `executive`),
  overridable from the StoreProfile — but enforcement is **opt-in and default OFF**
  (`FULFILLMENT_APPROVAL_TIERS_ENABLED`).
- `policy/action_authority_matrix.py` defines a `DUAL_CONTROL` decision and a rule that
  *"Supplier payment requires dual-control authorisation"* — but it is wired into
  `supplier_communication.py`, `escalation_policy.py`, `auth.py` and `route_enforcement.py`,
  **not into the fulfillment FSM or `fulfillment_cases.py`**. And `supplier_communication` is
  explicitly a *compatibility surface*: production delivery uses `fulfillment/external_comms`,
  with an architecture test forbidding application code from calling the retired dispatcher.
- **No check anywhere that the approver differs from the requester.** No four-eyes, no
  maker-checker on the procurement path.

So today the FSM enforces **role** (must be `HUMAN_OPERATOR`) and optionally **tier** (flag-off
by default), but never **distinct identity**. One operator can request, approve and send. For a
pilot with a single operator that is survivable and honest; for anything beyond it, it is the
first control an auditor will ask for.

### 6.3 What is needed to widen autonomy, in order

1. **Enforce SoD** — approver `user_id` ≠ requester `user_id`, on `approval_granted`,
   `supplier_quote_validated` and `purchase_order_approved`. The identity is already captured;
   this is a comparison and a test.
2. **Turn approval tiers on** and pin the StoreProfile ladder. Default-off is the wrong default
   once real money is involved.
3. **Wire `DUAL_CONTROL` into the procurement FSM** for PO approval above the director tier.
4. **Move the confidence gate onto the send row**, not just the approval row.
5. **Seal the dispatch-absence certificate** — a live journey proving zero outbound messages.
6. Only then consider enabling `FULFILLMENT_AUTONOMOUS_RFQ`, and start it at a value cap well
   below the $5,000 default.

---

## 7. What is left, prioritised

### Now — unblocks the buyer demo

| # | Item | Why |
|---|---|---|
| 1 | **Governed derivation ledger** — versioned rules + approval provenance + observed/derived/accepted tri-state | The *only* thing between correct evidence and a qualified shelf (§4). Do not relax the gate instead |
| 2 | **Resolve `attribute_not_registry_authorized`** for the PRAGMATA attribute set | Second half of the same failure |
| 3 | **Seal the positive delivery browser gate** — complete evidence + matching stock ⇒ non-empty qualified shelf, zero retries | The one gate that has never gone green |

### Next — unblocks the pilot

| # | Item | Why |
|---|---|---|
| 4 | **SoD enforcement** (approver ≠ requester) | §6.2 — the first control an auditor asks for |
| 5 | **Live cart-confirm → operator-draft seam test** | The one procurement seam never exercised end to end |
| 6 | **Dispatch-absence certificate** + independent budget/stock shortfall tests | §3.3 gaps 2 and 3 |
| 7 | **Reconcile the 15 trace panels to terminal truth** | Navigation was proven; content contradictions were not fixed |
| 8 | **Decide the ranking-nudge experiment** — re-wire or retire | §2.1: a shipped console pointing at a dead lever |

### Then — production grade

| # | Item |
|---|---|
| 9 | Clean **PostgreSQL** certification + a real row-lock concurrency run on the money path |
| 10 | Clean-machine / hosted certificate (the current "clean checkout" reuses this interpreter) |
| 11 | Independent human source review (Rockwell is still 1 of 20 pending) |
| 12 | Extract terminal projection (~620 ln) and research entry (~900 ln) from `_chat_query_impl` — clears the last size breaches |
| 13 | Archive `recommendations.py` (382 det/kloc) and decide `orchestrator.py`'s fate (3,929 ln, unreachable from chat) |

---

## 8. Method and honest limits

**Ran:** AST analysis of `chat.py` and the FSM transition table; offline execution of
`parse_budget` / `_extract_budget_bounds`, `build_case_catalog_candidate_set`,
`_identity_subject_match`; full `tests/services` + `tests/integration` + `tests/architecture`
sweep; the complete 43-file procurement suite; the size guard; alembic head check; live probes
of `/health`, `/readyz`, the storefront, admin, SearXNG and Ollama.

**Live stack state at time of writing:** API, storefront (5173), admin (3001) and SearXNG (8888)
all returning 200; `qwen3:14b` resident at 9.65 GB VRAM. The cold-load bugcheck risk that
constrained my previous two assessments is currently absent.

**Did not run:** a live end-to-end procurement journey. Creating a case, drafting to a supplier
and exercising the approval ladder are outward-facing actions against a warm stack — that is
your call to authorise, not mine to take unprompted. §3.3 lists exactly what such a run must
assert; if you want it, say so and I will script it read-only first (draft and inspect, no
approval, no send).

**Not certified by anything in this report:** clean PostgreSQL, a clean machine, hosted
deployment, or any independent human source review.
