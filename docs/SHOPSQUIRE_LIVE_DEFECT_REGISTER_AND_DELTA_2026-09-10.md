# ShopSquire — Live Defect Register & 24-Hour Delta

**Date:** 2026-09-10 · **HEAD:** `516710c0` · **Working tree: CLEAN (0 dirty files)**
**Delta window:** 2026-09-09 → 2026-09-10 — 5 commits, 87 files, **+4,752 / −1,644**
**Prior:** `SHOPSQUIRE_PILOT_READINESS_AND_PROCUREMENT_ASSESSMENT_2026-09-09.md`

Evidence: five live journeys run against the warm stack via `/api/v1/chat/query` (two-phase
idempotency protocol), plus AST/offline execution of the implicated functions. Chat turns only —
**no cart, supplier, approval or payment action was taken.**

---

# PART 1 — Delta since yesterday

## 1.1 The architecture debt is cleared

**All six source-size ceilings now pass. `scripts/check_source_file_sizes.py` exits 0 for the
first time in this arc**, and the full `tests/architecture` suite is green.

| File | 09-09 | Now | Ceiling |
|---|---:|---:|---:|
| `routers/chat.py` | 5,787 | **5,008** | 5,049 ✅ |
| `routers/shopping_cases.py` | 2,397 | **2,065** | 2,073 ✅ |
| `routers/fulfillment_cases.py` | 2,574 | **2,439** | 2,447 ✅ |

Achieved by real extraction, not by raising limits — `chat_turn_projection.py` (225),
`chat_image_security.py` (250), `chat_cart_projection.py` (176), `chat_transport.py` (160),
`chat_persistence.py` (75), `catalog_shortfall_projection.py` (74),
`schemas/shopping_case.py` (156), `shopping_case_trace_reader.py` (146).

This closes the recommendation I made on 09-07 (extract terminal projection + research entry).

## 1.2 A false certificate was caught and fixed

From `SHOPSQUIRE_COMPATIBILITY_AND_POSTGRES_DELTA_2026-09-10.md`:

> *"The old PostgreSQL runner silently entered SQLite test isolation."*

Every previous "PostgreSQL" claim in this project was actually SQLite. The replacement runs
outside that conftest, asserts the real dialect/database/migration head, **rejects skipped
required tests**, and cleans up only its own container. A real PostgreSQL 16 migration to
Alembic head now passes, plus a durable sourcing test proving an accepted draft persists across
sessions, replays idempotently, and adds **no** `outbound_message` or `outbound_delivery_job`
row. That is a genuine partial answer to the dispatch-absence gap I raised on 09-09.

Also landed: typed comparison delegation in `accepted_catalog_projection::_verdict` (substrings
are no longer treated as compatibility); the model extractor now rejects textual values absent
from their quoted span; freshness alone no longer confers verification on derived observations.

## 1.3 Delta scorecard

| 09-09 item | Status |
|---|---|
| Extract terminal projection / research entry | ✅ done — ceilings clear |
| Clean PostgreSQL certification | 🟡 partial — real PG 16 migration + durable sourcing certificate; not a full-suite PG run |
| Dispatch-absence certificate | 🟡 partial — proven at the handler/DB layer, not in a live browser journey |
| Governed derivation ledger | ⛔ open — still the delivery blocker |
| SoD enforcement (approver ≠ requester) | ⛔ open |
| Ranking-nudge experiment (dead lever) | ⛔ open |

---

# PART 2 — Live defect register

Twelve defects, all reproduced today. Ordered by buyer impact.

## D1 · "about 3000" silently becomes AUD 3,600 🔴

**File:** `src/app/services/budget_grammar.py:353`, `:380`, `:393`

```python
return BudgetParse(int(v * 0.8), int(v * 1.2), "around", m.span())
```

**Live evidence (J2.1):** `budget 2400..3600 (around)` for *"…for about 3000"*. Screenshot 033
shows the trace stating **budget AUD 3,600** for a buyer who said 3000.

A ±20% band is invented from a number the buyer stated. The buyer never authorised 3,600.
`around|about|roughly|approx*|~` all hit this.

**Fix:** the stated number is the anchor, not a band midpoint. Set `budget_max = v`; if a
tolerance is wanted, it must be visible in the UI as a separate "stretch to X" affordance the
buyer opts into.

## D2 · The stretch shelf is unbounded 🔴

**File:** `src/app/services/recommendation_core/product_shelves.py:599`

```python
stretch = [item for item in eligible if item.commercial_decision.budget_outcome == "over"]
```

Any product over budget qualifies, at any distance. **Screenshot 034** shows a buyer who said
3000 being offered **$3,899 / $4,599 / $4,799** — 60% over stated, and over even the inflated
3,600.

**Fix:** cap the band (e.g. ≤ +15% of `budget_max`) and drop the remainder.

## D3 · "Publisher ownership verified" is claimed from identity alone 🔴 (governance)

**File:** `src/app/services/research_outcome.py:374-377`

```python
elif (authority_values | accepted_authority_values) & {"verified","verified_official","publisher_verified"} \
     or (identity and compiled):
    ownership = "verified"
```

**Rendered at:** `frontend/src/components/ResearchOutcomeSummary.tsx:38`

The `or (identity and compiled)` clause treats *a resolved identity plus any compiled
requirement* as corporate-ownership verification. **Screenshot 033** shows the resulting
contradiction on one screen:

- header: **"Publisher ownership verified · Kingdom Come: Deliverance II"**
- body, directly below: **"Possible publisher sources — ownership not yet verified"**
- trace: **"Corporate ownership authority: not independently verified"**

This is precisely the failure class you named: *claiming verification while the trace says
incomplete.*

**Fix:** delete the `or (identity and compiled)` clause. Identity resolution is not ownership
verification.

## D4 · A stale shelf survives an authority downgrade 🔴

**Files:** `frontend/src/App.tsx:2774` and `:1897`

```js
// 2774 — only refreshed on these conditions
if (!continuesActiveCase || revisionAdvanced || materiallyAmendsActiveCase) { setProductShelves(...) }
// 1897 — sets when present, NEVER clears when absent
if (terminal?.product_shelves?.schema_version === 'product-shelves-v1') setProductShelves(...)
```

Shelf state is additive; authority is not. When a turn continues the same case at the same
revision and authority flips to `blocked`, the previous shelf stays on screen.

**Screenshot 034:** trace reads **"0 accepted, 7 held · catalog authority blocked"** while the
panel still shows *"Verified fit — Exact-configuration evidence meets 2 accepted requirements."*

**Fix:** always mirror the terminal payload. When `catalog_authority !== 'permitted'`, clear the
shelf unconditionally — the clear paths already exist at `:1892` (out-of-category) and `:2736`
(upload); the authority-downgrade case is simply missing.

## D5 · Held-claim narration hijacks every later turn in the case 🔴 — *this is screenshot 037*

**File:** `src/app/services/terminal_research_narration.py:73-95`

```python
if held <= 0:
    return str(existing_message or "")
...
return (f"I found the official source for {title} and parsed {parsed} cited requirement claim...")
```

`held_claim_count` is **case-scoped**, but this override is applied **per-turn** with no check
that the current turn is about that workload. Once a case carries held claims, every subsequent
answer is replaced.

**Live reproduction (J2.3), a fresh three-turn case:**

| Turn | Buyer said | Assistant answered |
|---|---|---|
| 1 | KCD2 for about 3000 | publisher-source list |
| 2 | also run Emulate3D locally | 16 claims held |
| 3 | **"better disaster recovery like a raid 5? what else to buy?"** | **"I found the official source for the named workload and parsed 16 cited requirement claims…"** |

The storage question was discarded entirely, and the follow-up question was *"For gaming, which
level fits?"*. Twenty laptops were rendered on a disaster-recovery turn.

**Crucially — the model gets this right.** In a *fresh* chat the identical sentence produces:

> *"Honest answer: we don't stock Data Storage Solutions. I can raise a supplier request for a
> quote if you'd like us to source it."* (J1, from `recommendation_core/envelope.py:390`)

So the intelligence layer already reasons correctly from "disaster recovery / RAID 5" to storage
and refuses honestly. **A deterministic narration override is throwing that answer away.**

**Fix:** apply the held-claims sentence only when this turn's resolved subject is the workload
those claims belong to; otherwise append it as a status line and never replace the answer.

## D6 · A pre-research clarification survives successful research 🟠

**File:** `src/app/services/recommendation_core/core.py:788-800`

The question *"I identified {subject}, but no enrolled authoritative provider returned current
requirements…"* is built **inside the core, before external research runs**. It is only cleared
when `terminal_research_reconciliation.reconcile_semantic_resolution` binds the concept **and**
catalog authority is not blocked. When authority stays `unknown` — which it does on every
`discovered_candidate` turn — the stale question survives.

**Live evidence (J2.1, J4):** both emit a successful research message *and* this question.
**Screenshot 033** shows the resulting pair of contradictory bubbles: *"resolved… qualified 10
catalog configurations"* next to *"no enrolled authoritative provider returned current
requirements."*

**Fix:** clear core-stage workload questions whenever the terminal outcome resolved that same
subject, independent of catalog authority.

## D7 · "Retry approved research" is bound to a stale plan identity 🟠 — *screenshot 036*

**Files:** `src/app/routers/shopping_cases.py:1789-1793` ·
`frontend/src/hooks/useShoppingCaseResearch.ts:308-310` · `frontend/src/App.tsx:3165`

```python
if (body.research_plan_id != plan.plan_id
        or set(body.ambiguity_object_ids) != expected_ambiguities
        or set(body.hypothesis_ids) != expected_hypotheses):
    raise HTTPException(409, {"code": "case_research_plan_mismatch", ...})
```

The client sends the plan identity **from React state**. Any turn that advances the case
regenerates the plan server-side, so the held identity goes stale and retry 409s **by
construction** after the buyer answers a clarification. Screenshot 036 shows the buyer answering
the system's own question (*"emulate 3d to simulate mechanical engines"*) and being told the
interpretation *"does not match the retained case plan"*.

**Cosmetic, same line:** `App.tsx:3165` appends a second period to a message that already ends
in one → the visible **".."**.

**Fix:** re-read the current plan before retrying, or accept a superseding plan by lineage.
Remove the duplicated period.

## D8 · Publisher ranking structurally favours aggregators over the real publisher 🟠

**File:** `src/app/services/open_world_research_discovery.py:98-127`

```python
if any(token in path for token in ("requirements", "system-requirements")): score += 8
if "requirements" in title:                                                score += 7
score += min(12, 6 * int(row.get("publisher_host_overlap_count") or 0))
```

Spec-aggregator sites are *literally named after the search term*, so they collect +15 before any
other signal, while a publisher like Deep Silver scores nothing for hostname overlap (its domain
does not contain the game's name).

**Live evidence (J4) — the ranked list offered to the buyer as "publisher sources":**

```
1 www.global-esports.news        5 can-i-run-it.com
2 technical.city                 6 gamesystemrequirements.com
3 www.pcgamebenchmark.com        7 sysrqmts.com
4 www.systemrequirementslab.com  8 www.deepsilver.com   ← the actual publisher
```

The buyer is asked to approve a source from a list where the correct answer is **last**. That is
the mechanism behind screenshots 033→034: an aggregator was approved, 7 claims were extracted,
and they were correctly held — but the ranking steered the buyer there.

**Fix:** the identity resolver *already knows the publisher*. Cross-reference that name/domain
against candidate hosts and rank an exact publisher-domain match first; demote hosts whose name
is a generic "system requirements" phrase.

## D9 · Irrelevant next-questions leak across subject changes 🟠

**Live evidence:**

| Turn | Question offered |
|---|---|
| J1 — storage refusal | *"Prioritize interactive performance or rendering/export speed first?"* |
| J3.2 — chair refusal | *"Can we widen your budget upward from your current range?"* |
| J2.3 — disaster recovery | *"For gaming, which level fits? It changes the pick and the price."* |

Nudging a buyer to widen budget for a product the store does not stock is the worst of these.

**Fix:** bind questions to the turn's resolved subject and scope; drop any whose slot does not
apply to the resolved category.

## D10 · `catalog_scope` does not reflect an off-catalog refusal 🟡

**Live evidence:** J1 and J3.2 both report `scope: el-6-6 (Laptops), source=buyer_explicit,
status=bound` while the message correctly refuses *Data Storage Solutions* / *Computer Chairs*.
The scope object and the narration disagree about what the buyer asked for.

**Fix:** when the refusal fires, set the scope to the refused node with an explicit
`out_of_category` status.

## D11 · The deterministic taxonomy cannot see storage intent 🟡

**File:** `src/app/services/case_catalog_candidates.py::_explicit_category` — requires an exact
node-name match.

Measured:

```
_explicit_category("...disaster recovery like a raid 5...")  -> None
_explicit_category("i need a NAS")                            -> None
_explicit_category("raid 5 storage")                          -> None

search_nodes("NAS")   -> Bandanas & Headties · Nasal Aspirators · Antennas · Saunas
search_nodes("raid")  -> Hair Braiders · Fishing Braids · el-7-9-14-3-2 Portable RAID Enclosures
search_nodes("network attached storage") -> []
search_nodes("disaster recovery")        -> []
```

A `Portable RAID Enclosures` node exists but is unreachable, and "NAS" substring-matches
*Saunas*. With no match, the builder falls back to the storefront default and declares
`status=eligible` on **Laptops**.

**This is your Synology point.** The right split is the one the platform already half-implements:
**the model proposes the category (it does this well — J1 proves it), the deterministic layer
only clamps that proposal against the sold taxonomy and never silently substitutes the storefront
default.** Do not fix this by adding NAS/RAID keyword lists.

## D12 · Provisional shelves render with zero accepted evidence 🟡

**Live evidence:** J2.1 — 15 products across 6 shelves with `research=degraded`, `accepted=0`,
`authority=unknown`. J2.3 — 20 products across 8 shelves on a **disaster-recovery** turn in a
laptop-scoped case.

**Fix:** never render provisional shelves on a turn whose resolved subject changed category.

---

# PART 3 — Journeys run today

| # | Journey | Result |
|---|---|---|
| J1 | Fresh chat: *"disaster recovery like a raid 5"* | ✅ **honest refusal** — "we don't stock Data Storage Solutions" · 0 products · but D9, D10 |
| J2 | KCD2 → +Emulate3D → disaster recovery (one case) | ❌ **reproduces screenshot 037** — D1, D5, D6, D12 |
| J3.1 | *"Laptop under AUD 3,000"* | ✅ budget band correct, 10 options |
| J3.2 | → *"Actually, a computer chair under AUD 400"* | ✅ **category switch correct** — budget 400, honest refusal, no inherited hardware reqs · but D9, D10 |
| J4 | *"What laptop do I need for KCD2, under AUD 3,000?"* | ⚠️ identity resolved; **publisher ranked 8th** (D8); stale clarification (D6) |

**What works well and should not be disturbed:** the category-switch journey, the fresh-chat
off-catalog refusal, budget parsing for `under`/`up to`, and — most importantly — the model's
own categorisation of "disaster recovery / RAID 5" as storage. The intelligence is doing its job.
Nine of the twelve defects are deterministic layers discarding or contradicting a correct model
answer.

---

# PART 4 — Fix order

| # | Defect | File:line | Effort |
|---|---|---|---|
| 1 | **D5** held-claim narration hijack | `terminal_research_narration.py:73-95` | small — subject check before override |
| 2 | **D3** ownership claimed from identity | `research_outcome.py:374-377` | one clause deletion |
| 3 | **D4** stale shelf on authority downgrade | `App.tsx:2774`, `:1897` | small |
| 4 | **D1** budget inflation | `budget_grammar.py:353,380,393` | small — plus a decision from you |
| 5 | **D2** unbounded stretch band | `product_shelves.py:599` | small |
| 6 | **D6** stale pre-research clarification | `core.py:788-800` | medium |
| 7 | **D8** publisher ranking | `open_world_research_discovery.py:98-127` | medium — reuse the resolved publisher |
| 8 | **D7** stale plan identity on retry | `shopping_cases.py:1789`, `useShoppingCaseResearch.ts:308` | medium |
| 9 | **D9/D10/D12** question, scope and shelf leakage across subject change | several | medium — one "turn subject changed" predicate serves all three |
| 10 | **D11** model-proposes / deterministic-clamps for category | `case_catalog_candidates.py` | larger — architectural, do last |

Items 1–5 are roughly a day and remove every contradiction visible in your five screenshots.

---

# PART 5 — Decisions I still need from you

1. **Budget semantics (D1).** Does *"about 3000"* mean *"3,000 is my number"* or *"3,000 ± a bit,
   show me the bit"*? My recommendation: treat the number as the ceiling, and offer any stretch
   as an explicit, labelled opt-in. This is a product decision, not a bug fix.
2. **Independent reviewer** for source authority and CPU/GPU equivalence — still outstanding, and
   still the gate on the governed derivation ledger. Rockwell remains 1 of 20 sources pending.
3. **Hosted staging destination and owner**, with credentials supplied through a secure channel —
   never a screenshot or this chat.
4. **First additional category** (coffee / groceries / other) with representative inventory,
   packaging and unit definitions, and its responsible reviewer.

A missing shelf when evidence is incomplete is correct behaviour. **D3 and D4 are real bugs by
your own definition — they claim verification while the trace says otherwise.**

---

## Method

Five live journeys through `/api/v1/chat/query` with the two-phase idempotency protocol; offline
execution of `parse_budget`, `_explicit_category`, `search_nodes` and `_quality_score`; AST/line
inspection of every implicated file; `tests/architecture` and the size guard re-run. Stack warm,
`qwen3:14b` resident. No cart, supplier, approval or payment action was taken, and no durable
sourcing record was created.
