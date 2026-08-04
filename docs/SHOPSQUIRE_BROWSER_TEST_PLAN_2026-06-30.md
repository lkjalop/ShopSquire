# ShopSquire — Live Browser Clickthrough Test Plan

**Date:** 2026-06-30
**Purpose:** The exact behaviours to verify in a real browser (what only a human clickthrough can confirm — API/unit tests already pass). Run top to bottom; each test has **Steps → Expected → How to confirm (DevTools)** + a pass box.

---

## 0. Preconditions (do once before testing)

- [ ] **Backend restarted** AFTER the latest commits (the CORP fix `82fccbc` only takes effect on restart).
- [ ] **Frontend rebuilt / hard-refreshed** (Ctrl-Shift-R) so you're not on a stale bundle. If using the dev server, restart vite so it picks up `.env` + the new components.
- [ ] **Flags on** (env or `config/feature_flags.json`): `FULFILLMENT_DEFER_TO_CART=1`, `FULFILLMENT_CASES_ENABLED=1`, `COMMERCE_CATALOG_ENABLED=1`. Keep `FULFILLMENT_AUTONOMOUS_RFQ=0` (autonomy OFF).
- [ ] **DevTools open** → Network tab + Console tab, for every test.
- [ ] Two tabs ready: the **buyer storefront** (`:5173`) and the **admin** Procurement Control Room.

---

## 1. CORP / chat-stream fix — THE critical one (Gap 4)

**Why:** the previous blocker — chat sent a 200 but the panel didn't render (`ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`).

**Steps:** On the buyer storefront, type *"gaming laptop under 1500"* and send.

**Expected:** the assistant replies in the left chat panel AND product cards appear in the right panel.

**Confirm (DevTools):**
- Network: a request to `/api/v1/chat/stream` (or `/chat/query`) returns **200** AND its response is **readable** (not blocked).
- The response headers on `/api/...` show `cross-origin-resource-policy: cross-origin` (the fix).
- Console: **no** `ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`.

- [ ] **PASS** — chat renders, no NotSameOrigin error.
- If FAIL: confirm the backend was restarted; check whether the request goes to `:8080` (direct) and whether that response carries the CORP header above.

---

## 2. Buyer sourcing preview → confirm (the fluid-procurement core)

**Steps:** Send *"I need 15 laptops for the office, need them in one week, budget about 1500 each."*

**Expected:**
- Recommendations appear AND a **"Sourcing preview"** card renders ("needs confirmation before sourcing"), listing the line(s) and a **"Confirm sourcing from cart"** button.
- **No** durable case is created yet (this is just a preview).

**Steps (cont.):** Click **"Confirm sourcing from cart."**

**Expected:** the card shows *"Created N sourcing request(s) — the procurement team has been notified. No supplier has been contacted yet."*

**Confirm:** Network shows `POST /api/v1/fulfillment/cases/confirm-cart` → 200 with `case_count ≥ 1`.

- [ ] **PASS** — preview renders, confirm creates case(s), copy says no supplier contacted.

---

## 3. Mixed multi-line order (Gap 2 — adjective parsing)

**Steps:** Send *"20 gaming laptops + 20 headsets + 10 monitors, need in 10 days."*

**Expected:** the sourcing preview lists **all three** lines (laptops 20, headsets 20, monitors 10) — *not just laptops*. (This was the bug: "gaming" adjective dropped headsets.)

**Steps (cont.):** Confirm → admin Procurement queue shows **supplier-grouped** cases (e.g. a CreatorFleet group + a PeriLink group), each as a separate case sharing one order group.

- [ ] **PASS** — all three lines parsed; cases grouped by supplier in admin.

---

## 4. Admin: notification + margin at the send gate (E1 + sell engine)

**Steps:** In the admin Procurement Control Room (after test 2/3):

**Expected:**
- A **"N new procurement updates"** banner appears (the operator notification feed); "Mark all seen" clears it.
- Select a case → at the send-decision state you see a **margin banner**: verdict (healthy/thin/below_floor), *"You can offer the buyer up to $X"*, and the supplier's last invoiced price — **before** you approve the send.

**Confirm:** the margin shows real numbers (NOT `insufficient_data`) — this is the Gap-1 fix. If it says insufficient_data, the SKU has no catalog price (see Track C / seed prices).

- [ ] **PASS** — notification banner works; margin verdict + discount headroom shown at the gate.

---

## 5. Buyer changes their mind → amend / supersede (P4/P5)

**Steps:** After confirming an order (test 2), in the **same** session, send a different order for the **same intent** (e.g. change the laptop model/qty) and confirm again.

**Expected:** the card detects the change → shows *"already confirmed with different items"* + a **"Supersede & re-source"** button. Click it.

**Expected:** *"Updated — retired N earlier request(s) and created M new one(s). No supplier was contacted."* In admin, the old case(s) show **SUPERSEDED**; new case(s) are active.

- [ ] **PASS** — amendment detected; supersede retires old + creates new; admin reflects SUPERSEDED.

---

## 6. Human approval gate + (optional) supplier email (GATE 2)

**Steps:** In admin, take a committed case to draft → **request approval** → the case sits at **AWAITING_APPROVAL** ("HUMAN APPROVAL REQUIRED").

**Expected:** the supplier draft packet shows the recipient (resolved from allowlist, NOT buyer text), the RFQ body with a **concrete deadline date** (Gap 3 — "need in one week" → an actual date, not "the stated deadline"), shortfall quantities, "this is not a purchase order" footer, and the evidence packet.

**Confirm:** nothing is sent until a human clicks **Approve & send** (GATE 2). With autonomy OFF, the agent never sends.

- [ ] **PASS** — draft is complete (concrete deadline), gated behind human approval, supplier resolved from allowlist.

---

## 7. Cart → sourcing bridge (Gap 6)

**Steps:** Add an out-of-stock / high-qty item to the **normal cart**, then click **Checkout**.

**Expected:** the button briefly shows *"Checking stock…"*; if any line is short on stock, a note appears: *"N item group(s) are short on stock — a sourcing request was created… In-stock items can check out now"* + a **"Continue to checkout"** button. If everything is in stock, it goes straight to checkout.

**Confirm:** Network shows a `POST /confirm-cart`; the button never hangs (8s timeout).

- [ ] **PASS** — checkout routes short-stock lines to sourcing, in-stock proceeds, no hang.

---

## 8. Image security — malicious vs benign (Gap 5)

**8a. Malicious image:** upload a QR/steg-style test image with a query like *"gaming laptop."*
- **Expected:** a clear security notice ("a suspicious element… was detected and neutralised… logged for security review") AND recommendations still flow (warn-and-continue). The decision trace logs the security event.
- [ ] **PASS** — flagged + neutralised + products still shown.

**8b. Benign image:** upload a normal product photo (clean metadata) with the same query.
- **Expected (the fix):** **NO** scary "flagged by our security system" message — just a neutral basis line + recommendations.
- [ ] **PASS** — clean image does NOT alarm the buyer.

---

## 9. Decision trace + procurement journey (audit)

**Steps:** Open the **Decision Trace** on a procurement turn → the **Procurement tab** (not "All Events").

**Expected:** you see the procurement agent events (Supplier_Selection_Agent after a case exists; Procurement/Alternatives agents; market-intel if enabled) + the case **journey** (NEW → AVAILABILITY_ASSESSED → … → AWAITING_APPROVAL).

- [ ] **PASS** — procurement agents + journey visible on the Procurement tab.

---

## 10. 409-replay UX (E1)

**Steps:** In admin, double-click an action (or repeat a confirm) to force a 409.

**Expected:** a **calm** notice — *"That action was already applied — refreshing the case"* (or "the case has already moved past this step") — and the view refreshes to the real state. **Not** a raw "409 Conflict" error.

- [ ] **PASS** — 409 reads as a calm refresh, not a scary error.

---

## Quick pass/fail summary

| # | Test | Pass? |
|---|---|---|
| 1 | CORP / chat renders (no NotSameOrigin) | ☐ |
| 2 | Sourcing preview → confirm | ☐ |
| 3 | Mixed order parses all lines + grouped | ☐ |
| 4 | Notification + margin at the gate | ☐ |
| 5 | Amend → supersede | ☐ |
| 6 | Human approval gate + concrete deadline | ☐ |
| 7 | Cart → sourcing bridge | ☐ |
| 8 | Image: malicious flagged / benign calm | ☐ |
| 9 | Decision trace + journey | ☐ |
| 10 | 409-replay calm UX | ☐ |

**If #1 passes, the rest should flow.** If #1 fails, stop and capture the Network request + Console error — that's the one environment-level unknown left, and it tells me exactly what to fix.
