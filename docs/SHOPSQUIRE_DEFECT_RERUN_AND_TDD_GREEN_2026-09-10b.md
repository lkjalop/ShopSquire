# ShopSquire — Defect Re-run, 8-Hour Delta & What "Green" Must Mean

**Date:** 2026-09-10 (evening) · **HEAD:** `ad65cee4`
**Window:** ~8 hours — 2 commits (`409f919b`, `ad65cee4`), 44 files, **+1,160 / −93**, plus a dirty tree
**Re-runs:** every defect D1–D12 from `SHOPSQUIRE_LIVE_DEFECT_REGISTER_AND_DELTA_2026-09-10.md`,
re-executed live today against the running stack
**Also answers:** the independent reviewer's five corrections to my register

---

## 0. Verdict

**The headline screenshot failure is fixed.** Screenshot 037 — the disaster-recovery turn that
came back as stale Emulate3D narration with 20 laptops — now returns:

> *"Honest answer: we don't stock Storage Devices > Hard Drive Arrays > Portable RAID Enclosures.
> I can raise a supplier request for a quote if you'd like us to source it."*

…with scope `el-7-9-14-3-2`, zero products, no stale narration and no gaming question. And it got
there via `src=validated_semantic_proposal` — **the model proposes the category, the deterministic
layer clamps it against the sold taxonomy.** That is the architecture I recommended and the
reviewer recommended, now actually running.

**Seven of twelve defects are closed, three partially, two open.** The two that remain open are
the two I ranked lowest, which is the right order.

**Three of the reviewer's five corrections to me are right and I concede them below.** One of
them — the ranking-nudge claim — was a straightforward research error on my part.

---

## 1. Defect re-run (executed today)

| ID | Defect | Status | Evidence |
|---|---|---|---|
| **D1** | "about 3000" → AUD 3,600 | ✅ **FIXED** | `parse_budget("about 3000")` → `{min: None, max: 3000, mode: "around"}`. The anchor survives *and* the approximate label is retained — better than collapsing it to a hard ceiling |
| **D2** | Unbounded stretch shelf | ✅ **FIXED, better than I proposed** | `StretchConsent` schema + `stretch_budget_cents` threaded through `project_accepted_catalog`; `product_shelves.py:386` raises `stretch_must_exceed_a_known_budget`. Explicit consent with a cap, **no invented percentage** |
| **D3** | Ownership claimed from identity alone | ✅ **FIXED** | `or (identity and compiled)` removed from the ownership branch; now requires a row with `publisher_ownership_status == "verified"`. Live: `ownership = discovered_candidate`, not "verified" |
| **D4** | Stale shelf survives authority downgrade | ✅ **FIXED** | New `frontend/src/lib/terminalShelves.ts` returns `null` on blocked/absent authority; installed **unconditionally** at `App.tsx:1907` and `:2464`; carries its own unit test |
| **D5** | Held-claim narration hijack | ✅ **FIXED** | The RAID turn (above). Regression written: `live-unresolved-purchase-boundary.spec.ts::held workload cannot answer a new unresolved purchase` |
| **D6** | Pre-research clarification survives success | ❌ **OPEN** | Reproduced twice today. Main message: *"I resolved Kingdom Come: Deliverance II … qualified 1 catalog configuration"*; alongside it: *"I identified kingdom come deliverance 2, but no enrolled authoritative provider returned current requirements."* **This is screenshot 033's contradiction, still live** |
| **D7** | Retry bound to stale plan identity | 🟡 **partial** | Server-side 409 correctly retained (the reviewer is right that it should be); client-side refresh is the remaining half |
| **D8** | Publisher ranking favours aggregators | ❌ **OPEN, unchanged** | Live re-run returned the identical order: global-esports.news, technical.city, pcgamebenchmark, systemrequirementslab, can-i-run-it, gamesystemrequirements, sysrqmts, then **deepsilver.com 8th** |
| **D9** | Irrelevant questions leak | 🟡 **partial** | Gone on subject change; D6 is the surviving instance |
| **D10** | scope ≠ purchased object | 🟡 **partial** | RAID now resolves correctly. **New instance found:** the Emulate3D turn resolved scope to `so-1` (*Software*) while the buyer is purchasing a computer |
| **D11** | Storage/RAID intent unreachable | ✅ **FIXED** | `el-7-9-14-3-2` now reached through model proposal + taxonomy clamp — no NAS/RAID keyword list was added |
| **D12** | Provisional shelves with zero accepted evidence | 🟡 **partial** | Fixed on subject change. Still present same-category: a KCD2 turn returned **4 products / 2 shelves** with `research=degraded`, `accepted=0`, `authority=unknown` |

### New findings from today's runs

- **N1 · Count disagreement.** Chat said *"qualified **1** catalog configuration"* while the same
  payload carried **2 products across 2 shelves** and `accepted_claim_count = 4`.
- **N2 · Purchase-object scope error.** The "also run Emulate3D locally" turn set scope to
  `so-1` *Software*. The buyer is buying a computer; the workload is not the purchase object.
  Same family as D10, different direction.
- **N3 · The ownership inference survives one level down.** `research_outcome.py:250`:
  ```python
  if identity and compiled:
      accepted = max(accepted, compiled)
  ```
  Now constrained to rows with `provider_id`, `source_url` and `status == "resolved"` — tighter
  than before, but still an **inference rather than a receipt**. The reviewer called this
  correctly.
- **N4 · Case continuity across an abandoned purchase.** The RAID turn opened a **new case at
  revision 2** while the prior case sat at revision 3. Correct in spirit — it is a different
  purchase — but nothing expresses the relationship between the abandoned case and the new one.

---

## 2. Corrections I accept

The independent reviewer made five corrections to my register. Three are right, one is right with
a qualification, and one I'd frame slightly differently.

**1. "Architecture debt is cleared" was too strong — accepted.** I conflated *the ratchet passes*
with *the debt is gone*. `chat.py` is still 5,008 lines, `App.tsx` and `DecisionTrace.tsx` both
exceed 4,000, and cross-category attribute/derivation unions remain on some fit paths. The correct
statement is: **the size guard exits 0 for the first time**, which stops the bleeding; it does not
mean the files are the right size.

**2. The ranking-nudge experiment is wired — accepted, my error.** I claimed "zero references in
`recommendation_core`" and concluded the lever was dead. The wiring is at
`recommendation_facade.py:839 `_run_v2_intelligence_stage`, whose own docstring says the stage
*"used to be reachable only from the legacy `suggest()` body"*. I scoped my search to the wrong
package and drew a conclusion from its absence. I re-ran `test_ranking_nudge_wiring` today: **0
failures.** My finding was wrong; withdraw it.

**3. "The model is right, deterministic layers throw it away" needs qualifying — accepted.** That
framing held for 9 of 12 defects but is not uniform. The Emulate3D turn carried a ~23.8-second
router timeout whose outer receipt was relabelled "unavailable" with deadline `0` — a real model
failure *and* a receipt that misdescribed it. Better framing: **the intelligence layer is more
often right than the surfaces that consume it, and both can fail.**

**4. Deleting one ownership clause is insufficient — accepted, confirmed above (N3).**

**5. My "+15% stretch cap" suggestion was wrong — accepted.** It would have replaced one invented
percentage with another. The implemented `StretchConsent` — explicit, capped, buyer-chosen — is
the correct answer, and it is better than what I proposed.

Where I'd add nuance rather than concede: the reviewer notes the targeted suites passed (102, then
173, then 114) and says this "exposes gaps in what those tests assert." Agreed — and that is
exactly the subject of §3.

---

## 3. What "green" must mean — a TDD reassessment

The reviewer's seven-point definition of green is right. What follows is the *testing* argument
underneath it: **why this project keeps producing passing suites alongside broken journeys**, and
what class of test closes the gap.

### 3.1 The pattern: tests that cannot fail for the reason you care about

Three documented instances, all from this project, all found in the last week:

| Instance | Why it couldn't fail |
|---|---|
| `if (scenario.name === 'pragmata' && accepted_claim_count > 0) { expect(shelfProducts.length).toBeGreaterThan(0) }` | The assertion **skipped itself** exactly when delivery failed |
| *"The old PostgreSQL runner silently entered SQLite test isolation"* | The certificate tested a **different system** than the one it named |
| 173 backend tests green while five browser journeys fail | Every test asserted **one surface in isolation**; every defect was a **disagreement between surfaces** |

The third is the important one, and it is structural. D1, D3, D4, D6, D10, D12 and N1 are all the
same shape: *surface A says X, surface B says not-X, and both are internally consistent.* No
per-surface unit test can ever catch that. You need an assertion whose subject is the
**relationship**, not the value.

### 3.2 The green ladder

| Level | Question it answers | Project status |
|---|---|---|
| **L0 Unit** | Does this function do what its name says? | ✅ strong — 1,271 test files |
| **L1 Contract** | Does this typed boundary honour its schema and refuse correctly? | ✅ strong — the compiler/scope/authority work is exemplary here |
| **L2 Journey** | Does a multi-turn browser sequence reach the right end state, zero retries? | 🟡 emerging — 4 new live specs today, `retries: 0` enforced |
| **L3 Invariant** | Do all surfaces agree, at **every** turn of **every** journey? | ❌ **essentially absent — this is the gap** |
| **L4 Certificate** | Clean checkout, real PostgreSQL, hosted, WORM, independent review | ❌ not started |

**L0 and L1 green is what the project has. L2 and L3 green is what the screenshots demand.** That
is the whole explanation for "173 tests pass, five journeys fail."

### 3.3 The seven invariants worth writing

Each is one assertion, evaluated after **every turn** of **every** live journey, over chat + right
panel + all 15 trace leaves. They are cheap, and between them they would have caught eleven of the
twelve defects.

| # | Invariant | Would have caught |
|---|---|---|
| **I1 Subject** | Every surface names the same purchase object as `terminal.catalog_scope` | D10, D11, N2 |
| **I2 Budget** | Literal input, retained constraint and every displayed figure agree; no surface shows a number the buyer neither stated nor consented to | D1, D2 |
| **I3 Authority monotonicity** | If `terminal.catalog_authority !== 'permitted'`, **no** surface shows a qualified or verified product | D3, D4 |
| **I4 Recency** | No surface renders content from a revision older than `terminal.case_revision` | D4, D5, D6, D12 |
| **I5 Provenance** | No "verified" / "approved" / "you approved" wording anywhere without a matching receipt id in the payload | D3, N3, the "you approved" defect |
| **I6 Question relevance** | Every rendered question's slot is applicable to the terminal scope | D6, D9 |
| **I7 Commerce** | Zero POSTs to confirm-cart / send-approved / send-autonomous / payments on a read-only journey | — (already implemented) |

**I7 already exists** — `live-unresolved-purchase-boundary.spec.ts:92` records those requests so
the test can assert none occurred. That is the pattern; it needs to be generalised to a shared
helper the other six use.

Two further points on the same page that deserve keeping:

- Line 38: `expect(qualified.length, 'Live evidence and matching inventory must actually deliver
  qualified products').toBeGreaterThan(0)` — **unconditional, with a message.** This is the
  positive delivery gate I said was missing. It now exists, written before the fix, in the correct
  TDD order.
- Line 52: `expect(terminal.right_panel.canonical_budget).toEqual(budget)` — **an I2 invariant,
  already written.** The habit is forming; it needs to become a rule.

### 3.4 The one rule

> **A test is only worth counting as green if it can go red for the reason you care about.**

Practically, three checks before a test counts:

1. **It failed first.** The receipts in this project already state "failed before the change" —
   keep that, and record the red message, not just the fact.
2. **No conditional on the property under test.** If the assertion is inside an `if` whose
   condition is the thing being tested, it is decoration.
3. **It asserts at the layer where the buyer experiences the defect.** A narration hijack is not
   caught by a unit test of the narration function — it is caught by a two-turn journey asserting
   that turn 2's answer is about turn 2's subject.

### 3.5 What green means for the remaining work

| Item | Green means |
|---|---|
| **D6** | A turn whose research resolved the subject emits **exactly one** account of that subject. Test: assert the turn's questions do not contradict its own message |
| **D8** | The resolved publisher's domain ranks first among candidates; a requirements-aggregator title confers no publisher authority. Test: KCD2 → `candidates[0].domain` contains the resolved publisher |
| **D10/N2** | Scope equals the purchase object, never the workload. Test: "laptop that also runs Emulate3D" → scope is a computer node, not `so-1` |
| **D12** | Provisional shelves are labelled distinctly and never appear with `accepted_claim_count == 0` and `authority == unknown` |
| **N1** | The count in the message equals the count in the payload |
| **N3** | Accepted counts derive from acceptance receipts, not from `identity and compiled` |
| **Delivery** | Complete authorized requirements + matching permitted inventory → non-empty qualified shelf, with the paired negative proving partial/held/incompatible evidence yields none |

---

## 4. Recommended order

1. **D6** — the last contradiction visible in the screenshots, and a small fix.
2. **Generalise I1–I6** into a shared per-turn assertion helper, then attach it to the four live
   specs that already exist. This is the highest-leverage item in the whole list: it converts every
   existing journey into a consistency test at near-zero marginal cost.
3. **N3** — replace the `identity and compiled` accepted-count inference with a receipt.
4. **D10/N2** — purchase object vs workload in scope resolution.
5. **D12/N1** — provisional labelling and count agreement.
6. **D8** — publisher ranking using the already-resolved publisher.
7. **D7** — client-side plan refresh (keep the server's 409).
8. Then the release ladder: shortfall journeys, transport-level zero-dispatch, manifests, clean
   checkout / PostgreSQL / hosted / WORM, independent review.

---

## 5. Method and limits

Re-ran `parse_budget`, the ownership branch, the stretch guard and `terminalShelves` offline;
re-ran the exact screenshot sequence (KCD2 → Emulate3D → RAID) and a publisher-ranking journey
live against the running stack via `/api/v1/chat/query`; inspected the four new e2e specs; verified
the reviewer's five corrections against source. **No cart, supplier, approval or payment action was
taken; no durable sourcing record was created.**

**Backend sweep result (completed after the body was written): `tests/services` +
`tests/integration` + `tests/architecture` — **0 failures**, a handful of skips, exit 0. That is
the first fully clean backend sweep of this arc; the three runs before it carried 3–4 failures
(ranking-nudge x2, size guard, and an order-dependent flake). Note carefully what this does and
does not mean: it confirms L0/L1 green, and it is exactly the reading that §3 warns against
treating as buyer-delivery green — D6 and D8 remain reproducible live against this same clean
suite. Nothing in this document is a clean-checkout,
PostgreSQL, hosted or WORM certificate, and none of the outstanding human decisions
(independent reviewer, staging owner, first additional category) has been made.
