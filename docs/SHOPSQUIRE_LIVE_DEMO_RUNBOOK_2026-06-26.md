# ShopSquire — Live Demo Runbook (buyer → human → supplier → buyer)
**2026-06-26** · how to run the full auditable-procurement demo end-to-end, what to SEE at each step (bitemporal trace, the drafted email, what's about to be sent, the buyer panel, procurement options/alternatives), the GPT-5.5 browser clickthrough, what to confirm, and the honest gap list.

---

## 0. Bring-up — services, flags, seed, ports

**Three processes, three ports:**
| Surface | Port | What it is |
|---|---|---|
| Buyer app | **5173** | React/Vite — the shopper. Recommendations + the procurement panel. |
| Operator room | **3001** | admin-react — staff. Drafts, approvals, journey, deal economics. |
| API | **8080** | FastAPI backend. |

**Flags (set in `config/feature_flags.json` or env) — all default-OFF, turn ON for the demo:**
```
FULFILLMENT_CASES_ENABLED = 1     # recommend opens a procurement case on a bulk shortfall (GATE 1)
FULFILLMENT_DEMO_ENABLED  = 1     # enables the SANDBOX supplier reply + market replay endpoints
FULFILLMENT_BULK_THRESHOLD = 5    # order qty ≥ this triggers a case (set 2–3 for an easier demo)
COMMERCE_CATALOG_ENABLED  = 1     # economics reads canonical price_book / wholesale fallback
RECOMMEND_PIPELINE_V2     = 0     # leave off unless demoing the scatter-gather pipeline
```
> ⚠️ NEVER commit `config/feature_flags.json` from a demo run — restore with `git checkout config/feature_flags.json` after.

**Seed (so the supplier draft resolves + economics has data):**
```
PYTHONPATH=. python scripts/seed_suppliers.py
# → suppliers + trusted domains + supplier_products  AND  price_book_entry + inventory_level
```

**Operator auth:** the operator room calls owner-scoped endpoints. Set the owner key so the buttons aren't 401:
`localStorage.setItem('ss_owner_key', '<OWNER_API_KEY from .env>')` in the :3001 tab.

---

## 1. The demo narrative (what each click proves)

> "A buyer asks for **10 of an item we only have 4 of**. The agent does NOT email a supplier off a mere query (GATE 1). The buyer commits → the agent DRAFTS a supplier email (in a cage) → a **human** approves & sends (GATE 2) → a sandbox supplier replies → a human validates the quote → the buyer is shown **real fulfilment options** (ship-together / split / **substitute the shortfall** / reduce) → buyer selects → human approves & creates the PO → order completes. Every step is in a **bitemporal audit trail**."

### A. Buyer surface (:5173) — recommendations + procurement
1. Type a **bulk** query, e.g. *"I need 10 gaming laptops for an esports lab"*.
2. **Right panel / grid:** recommended products appear (`displayProducts` → ProductGrid + right panel). This is the "recommended products" the buyer sees.
3. Because qty 10 ≥ threshold and we're short, the recommend payload carries `fulfillment_case` → the **Procurement panel** renders (`FulfilmentOptions`, polling every 4s):
   - **GATE 1 copy:** *"N units need sourcing… we only contact a supplier after you confirm — nothing ordered, no delivery promised yet."* → **Confirm sourcing** button (`commit`).
4. After the operator generates options (step B), the buyer panel shows the **options with tradeoffs + flags** ("may miss deadline"), incl. **substitute the shortfall** = the *alternative* when we can't fully supply → **Confirm selection**.
5. After the operator finalizes, the buyer sees **"Order confirmed · reference PO-…"**.
6. **View journey** toggle → the buyer-safe **bitemporal** journey (redacted: no draft body, no wholesale, no supplier identity).

### B. Operator surface (:3001 → Procurement tab) — the human-in-the-loop
Select the case (it appears in the list). Each button = one workflow transition (the state machine enforces the actor + gates):
1. **Draft quote (agent)** → builds the supplier email *in a cage* (recipient from the trusted allowlist, never buyer text; no price; "not a purchase order" footer).
2. **The drafted email is visible** in the **Outbound draft** panel: To (recipient_domain), Subject, **Body**, the **content hash**, and the agent's **rationale** (scatter-gather evidence). *This is exactly "what is about to be emailed to the supplier."* Nothing has been sent yet.
3. **Request approval (agent)** → queues it; the **HUMAN APPROVAL REQUIRED** badge shows.
4. **Approve & send (GATE 2)** → `approval_granted` then the **hash-checked** human send. (Edit the draft after approval → the hash changes → the send is refused as `stale_approval`.)
5. **Trigger supplier reply** (SANDBOX SUPPLIER) → pick a scenario (full_quote / partial / late / substitute / expired / **untrusted_sender** / contradictory). Inbound is correlated + domain-verified (a spoofed domain → quarantined). The parsed quote shows with a **DEMO QUOTE RESPONSE** tag.
6. **Validate quote (HUMAN)** → expired quotes hard-reject.
7. **Generate options (agent)** → the buyer's panel (step A4) populates.
8. (buyer selects) → **Propose PO (agent)** → **Approve & create PO (HUMAN)** (idempotent, SANDBOX PO ref) → **Mark completed**.
9. **Deal economics** button → operator-only: supplier cost, margin %, **how much discount we can give the buyer and still clear the floor**, profit. *(This is the "what the platform makes / discount / supplier price / profit" ask.)*
10. **Journey (N)** panel → the full **bitemporal** trace: each `event → state by actor (reason)` with `valid_from` — the system-time/business-time audit.

### C. The decision trace (bitemporal)
- **Procurement journey** (case-level, the one above): `GET /api/v1/fulfillment/cases/{id}/journey` (full) and `GET /cases/{id}/as-of?t=<ts>` (reconstruct the case as it was at a past instant — the bitemporal proof).
- **Agent decision trace** (turn-level, the EXPLORE→EVALUATE→PLAN→ACTION reasoning + security signals): `DecisionTrace.tsx`, streamed over `…/decisions/{id}/events/ws`. Carries the `trace_id` the case was opened with (`source_trace_id`), so the recommendation decision and the procurement case are linked.

---

## 2. "Platform doesn't have all the items → procurement options + alternatives"

**How it works today:** the recommend availability stage computes `{requested_qty, in_stock, shortfall}`; on a **bulk** shortfall (`order_qty ≥ FULFILLMENT_BULK_THRESHOLD` and `shortfall > 0`) it opens the case at GATE 1 and the buyer panel offers procurement. `options.plan_options` returns the **alternatives**: ship-together, ship-available-then-remainder (split), **substitute the shortfall / substitute all** (query-relevant alternative products), or reduce — each with explicit tradeoffs; a deadline/budget miss is shown-but-flagged, never silently chosen.

**Two honest gaps to close for this to feel real in the demo (see §4):**
- The canonical **`inventory_level` is not yet wired into the availability assessment** — `shortfall` comes from the recommend stage's own stock count, not the catalog table I just built. So seeding `inventory_level` does NOT yet change what's "in stock" for the case.
- The trigger is **bulk-only** (`order_qty ≥ 5`). A normal single-item *"do you have X?"* where X is out of stock does **not** open a case. For a single-item "we don't carry it → here are alternatives" story, either lower the threshold to 2–3, or add a single-item out-of-stock trigger.

---

## 3. GPT-5.5 browser clickthrough (what the agent should do)

**Tab 1 — buyer (:5173):**
1. Enter *"I need 10 gaming laptops for an esports lab, budget $1800 each"* → submit.
2. Assert: recommended products render in the right panel; the **Procurement** panel shows status *awaiting buyer commitment*.
3. Click **Confirm sourcing**. Assert status → *committed*.
4. (wait for operator steps) → Assert options render; select **substitute the shortfall** (the alternative); click **Confirm selection**. Assert status → *selected*.
5. Click **View journey**; assert events are listed. Later assert **"Order confirmed · PO-…"**.

**Tab 2 — operator (:3001 → Procurement):**
6. Select the newest case. Click **Draft quote** → assert the **Outbound draft** panel shows To/Subject/Body + content hash (screenshot this — it's the headline artifact).
7. Click **Request approval** → assert **HUMAN APPROVAL REQUIRED** badge.
8. Click **Approve & send (GATE 2)** → assert state *quote sent*.
9. Choose scenario **full_quote** → **Trigger supplier reply** → assert parsed quote + **DEMO QUOTE RESPONSE** tag. (Also demo **untrusted_sender** once → assert quarantine.)
10. **Validate quote** → **Generate options** (now the buyer's tab 1 step 4 fires).
11. After the buyer selects: **Propose PO** → **Approve & create PO** → **Mark completed**.
12. Click **Deal economics** → assert margin + discount-headroom + profit. Click **Journey** → assert the bitemporal list ends at COMPLETED.

**What to surface (make sure these are visible/screenshotted):** the drafted email body + content hash; the GATE labels; the DEMO/SANDBOX tags; the parsed quote evidence; the deal-economics panel; the bitemporal journey; the buyer's options-with-tradeoffs (esp. the substitute alternative).

**What to fix if a click fails:** 401 on operator buttons → set `ss_owner_key`. No procurement panel on the buyer → check `FULFILLMENT_CASES_ENABLED` + qty ≥ threshold + a real shortfall. Draft → `NO_APPROVED_SUPPLIER` → run the seed script. No supplier reply option → `FULFILLMENT_DEMO_ENABLED`. Empty economics → no validated quote yet, or seed `price_book`/suppliers + `COMMERCE_CATALOG_ENABLED`.

---

## 4. What to test to confirm progress

**Automated (all green today — run these):**
```
pytest tests/services/fulfillment/ tests/services/test_commerce_catalog.py \
       tests/services/test_catalog_entities.py tests/services/test_shopify_catalog_adapter.py \
       tests/services/test_magento_catalog_adapter.py tests/services/test_market_analysis.py \
       tests/services/test_market_replay.py tests/integration/test_fulfillment_api.py \
       tests/test_*_migration.py tests/test_no_flavour_in_core.py tests/test_no_silent_except_in_core.py
```
This covers: the full state machine + 2 gates, PO finalization → COMPLETED, deal economics (incl. catalog JOIN + wholesale fallback), the canonical catalog + both platform adapters, the Track-B market detectors, single alembic head + drift, and the agnostic/observability ratchets.

**Manual (the live demo):** the §3 clickthrough on a running stack — this is the only thing the tests can't prove (browser + WebSocket + auth), and is the remaining confidence gap.

---

## 5. What's left for a polished live demo (prioritized)

1. **Wire `inventory_level` → availability** so seeding/syncing real stock actually drives the case's `shortfall` (today it doesn't). *Highest demo-value: makes "platform is short → procure" real and data-driven.*
2. **Single-item out-of-stock trigger** (or lower `FULFILLMENT_BULK_THRESHOLD`) so the common *"do you have X?" → "no, here are alternatives"* path opens a case, not just bulk orders.
3. **Live Playwright recording** of the §3 clickthrough (the `GATE_PROCUREMENT=1` harness exists in `tests/e2e/` but needs a running stack — can't run headless here).
4. **Operator UX polish:** editable draft before approval, inline quote-evidence spans, an as-of (time-travel) viewer in the journey panel.
5. **DecisionTrace ↔ case link in the UI:** a "Fulfilment journey" tab inside `DecisionTrace.tsx` (the data is linked by `trace_id`; the UI tab is the missing 193KB-file edit).
6. **Real market sources** beyond synthetic replay for the Track-B detectors (a real competitor/objection feed adapter), and the `market_signal → warehouse` sink when volume warrants.
7. **Production transports** (Phase 8): real outbound email + inbound poller + real PO system — today these are SANDBOX by construction.

> Items 1–2 are the only ones that change what the **buyer** sees in the demo; 3–5 are confidence/polish; 6–7 are post-demo productionization.
