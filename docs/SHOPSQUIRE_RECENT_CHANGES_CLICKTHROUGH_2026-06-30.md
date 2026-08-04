# ShopSquire — Recent-Changes Browser Clickthrough (permutations + confirm + unblock)

**Date:** 2026-06-30
**Scope:** ONLY the changes made this session — what a live browser must confirm, the buyer-behaviour permutations that exercise them, and what blocks each. (The general 10-scenario plan is in `SHOPSQUIRE_BROWSER_TEST_PLAN_2026-06-30.md`; this one is targeted at the new code.)

For each permutation: **Do → Confirm → Verifies (commit) → Blocked by.**

---

## 0. UNBLOCK FIRST (without these, the test is meaningless)

| # | Unblock | Why | Owner |
|---|---|---|---|
| U1 | **Restart the backend** | The CORP fix (`82fccbc`) only applies on restart — *the* likely reason chat didn't render | You |
| U2 | **Rebuild / hard-refresh the frontend** (Ctrl-Shift-R or restart vite) | Avoid a stale bundle (new components: SourcingIntentCard, the margin banner, 409 UX) | You |
| U3 | **Flags:** `FULFILLMENT_DEFER_TO_CART=1`, `FULFILLMENT_CASES_ENABLED=1`, `COMMERCE_CATALOG_ENABLED=1`, `FULFILLMENT_AUTONOMOUS_RFQ=0` | The fluid model + margin path require these; autonomy stays OFF | You |
| U4 | **Seed real retail prices** for the SKUs you'll test (e.g. LAP retail ~$1500 vs wholesale ~$1100) | Else margin reads `insufficient_data` / `thin` (P7) | You/me |
| U5 | **DevTools open** (Network + Console) every test | To confirm requests fire + no CORP error | You |

---

## 1. The permutations (each maps to a recent change)

### P1 — Chat renders cross-origin · **THE critical unblock**
- **Do:** send *"gaming laptop under 1500"*.
- **Confirm:** the assistant text + product cards render. Network: `/api/v1/chat/stream` 200 AND readable; its `/api/...` response header `cross-origin-resource-policy: cross-origin`. Console: **no** `ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`.
- **Verifies:** CORP fix (`82fccbc`).
- **Blocked by:** U1 (restart). *If this fails, stop — capture the Network entry + Console error; that's the one unknown.*

### P2 — Single bulk → fluid sourcing preview
- **Do:** *"I need 15 laptops for the office, need them in one week, budget about 1500 each."*
- **Confirm:** a **"Sourcing preview"** card ("needs confirmation before sourcing") with a **Confirm sourcing from cart** button; NO durable case yet.
- **Verifies:** fluid model (`b8b92cc`) + requirements capture.
- **Blocked by:** P1, U3.

### P3 — Mixed order, adjective parsing
- **Do:** *"20 gaming laptops + 20 headsets + 10 monitors, need in 10 days."*
- **Confirm:** the preview lists **all three** lines (not just laptops — the "gaming" adjective bug). Confirm → admin queue shows **supplier-grouped** cases.
- **Verifies:** Gap 2 mixed-order parsing (`2a728ec`).

### P4 — Concrete deadline in the supplier RFQ
- **Do:** confirm P2's order; in admin, draft the RFQ → open the supplier draft packet.
- **Confirm:** the body shows a **concrete deadline date** (today+7), NOT "the stated deadline"; completeness is satisfied.
- **Verifies:** Gap 3 requirements threading (`2a728ec`).
- **Blocked by:** U4 indirectly (case must materialize).

### P5 — Procurement continuity · **NEW this session, please test**
- **Do:** after P2's sourcing preview, in the **same session** ask *"can you do that cheaper?"* (or *"change it to 10"*).
- **Confirm:** the assistant **references your sourcing request** (e.g. "for your 15-laptop sourcing request, here's a cheaper split") rather than a cold new search.
- **Verifies:** Phase 1 continuity (`3709c25`).
- **Blocked by:** P1; needs Redis/session memory live.

### P6 — Bulk vs single narration (cache fingerprint)
- **Do:** send *"a gaming laptop"*, then *"50 gaming laptops"*.
- **Confirm:** the **50** query's prose mentions sourcing/bulk — it does NOT reuse the single-unit narration.
- **Verifies:** Phase 0 cache fingerprint (`40b2082`).

### P7 — Margin + discount headroom at the send gate
- **Do:** in admin, select a case at **AWAITING_APPROVAL**.
- **Confirm:** a **margin banner** auto-appears: verdict (healthy/thin/below_floor), *"You can offer up to $X"*, supplier last-invoiced price — **before** you approve the send. Should show **real numbers, not `insufficient_data`**.
- **Verifies:** sell engine (`9c5a146`) + the margin-data fix (`8b65a0c`).
- **Blocked by:** **U4 (real prices)** — if it says `insufficient_data`, the SKU has no catalog price.

### P8 — Amend after confirm → supersede
- **Do:** confirm an order, then confirm a **different** order (same session/order id), then click **Supersede & re-source**.
- **Confirm:** *"retired N earlier request(s), created M new one(s)"*; in admin the old case is **SUPERSEDED**, new is active.
- **Verifies:** P5 supersession (`5d0c73c`).

### P9 — Cart → sourcing bridge
- **Do:** add an out-of-stock / high-qty item to the **normal cart**, click **Checkout**.
- **Confirm:** "Checking stock…" → if short, *"N item group(s) are short on stock — a sourcing request was created… In-stock items can check out now"* + **Continue to checkout**. Never hangs (8s timeout).
- **Verifies:** Gap 6 bridge (`2a728ec`).

### P10 — Operator notifications
- **Do:** after any confirm/supersede, look at the admin Procurement Control Room.
- **Confirm:** a **"N new procurement updates"** banner; **Mark all seen** clears it; the queue auto-refreshes.
- **Verifies:** P3 notifications (`b315a92`).

### P11 — 409-replay calm UX
- **Do:** double-click an admin action (or repeat a confirm) to force a 409.
- **Confirm:** a **calm** *"That action was already applied — refreshing"* (or "moved past this step"), NOT a raw "409 Conflict".
- **Verifies:** E1 (`5d758db`).

### P12 — Image security: malicious vs benign
- **Do (a):** upload a QR/steg-style test image + *"gaming laptop"* → **Confirm:** flagged + neutralised notice AND products still shown.
- **Do (b):** upload a **clean** product photo + same query → **Confirm:** **NO** scary "flagged by our security system" message — just a neutral basis + products.
- **Verifies:** Gap 5 benign-image tone (`2a728ec`).

### P13 — Price consistency
- **Do:** browse any product grid / recommendations.
- **Confirm:** prices display consistently (no `$0` / whole-dollar-vs-cents mismatch).
- **Verifies:** F1 price reconcile (`75692ba`).

---

## 2. What needs CONFIRMATION (only a browser can tell us)
- **Chat actually renders** (not just a 200) — P1.
- **Sourcing card appears + confirm materializes cases** — P2/P3.
- **Continuity reference** in the assistant's follow-up reply — P5 (new).
- **Margin shows real numbers** at the gate — P7 (depends on U4).
- **Benign image doesn't alarm** — P12b.

## 3. What needs UNBLOCKING
- **U1 backend restart** — the gating blocker for P1 (and therefore everything).
- **U4 real retail prices** — blocks P7 reading "healthy" (will show `insufficient_data` without).
- If P1 still fails after U1/U2: a **Network + Console capture** is what unblocks me to fix it.

## 4. What I need BACK from you
- A pass/fail per permutation (P1–P13).
- **If P1 fails:** the Network entry (URL, status, `cross-origin-resource-policy` header) + the Console error string.
- **If P7 shows `insufficient_data`:** confirms we need to seed retail prices (U4) — tell me and I'll wire a price seed.
- **P5 (continuity):** the assistant's actual reply to "cheaper?" — does it reference your sourcing request?

**Minimum viable pass for a pilot:** P1 + P2 + P3 + P7 (with prices) + P8. Those prove the buyer→sourcing→margin→amend loop works in a real browser.
