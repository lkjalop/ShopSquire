# GPT‑5.5 — Full verify + fix‑and‑wire + roadmap brief (2026‑07‑02, session 2)

Paste everything below the line. This supersedes `GPT55_AUDIT_PROMPT_2026-07-02.md` — it covers a second
batch of fixes on top of the first. Your job: (A) run the automated checks, (B) do a browser clickthrough
of both surfaces following the exact steps, (C) for anything broken, diagnose → propose the fix + wiring
(file:line), and (D) produce a **detailed, prioritized roadmap**. Report a delta table + UI/UX findings +
the roadmap.

---

You are auditing ShopSquire on branch `wip/docker-real-env-20260213`. Two sessions of fixes have landed.
Verify they actually work, then hand back a prioritized roadmap.

## PART 0 — Setup (do this first)
- Services: backend `http://127.0.0.1:8080` · shopper `http://localhost:5173` · admin `http://localhost:3001`.
- **Hard‑refresh both frontends** (Ctrl/Cmd‑Shift‑R). Recent fixes land via Vite HMR; a stale bundle will lie to you.
- Auth keys (dev): merchant `local-merchant-key`, owner `local-owner-key`. In the admin app use the
  "Set API Key" modal; the shopper reads its key from `.env.development.local` (already set).
- **Multi‑intent is flag‑gated** (`MULTI_INTENT_PLANNER_ENABLED`, default OFF). The running backend has it ON
  via env for this session. If a chat response has `multi_intent: null`, set the flag in
  `config/feature_flags.json` (or env) and restart `:8080`.
- Do NOT touch `FULFILLMENT_AUTONOMOUS_RFQ` or the supplier transport — supplier send stays sandbox/OFF.

## PART 1 — Automated checks (run + record output)
1. Ratchets (must be green):
   `python -m pytest -q tests/test_no_flavour_in_core.py tests/test_no_silent_except_in_core.py tests/test_no_untimed_outbound_http.py`
2. The just‑fixed suites (must be green):
   `python -m pytest -q tests/services/test_market_pipeline.py tests/services/test_market_replay.py tests/integration/test_adaptive_growth_pipeline.py tests/security/test_auth_fail_closed.py tests/services/test_multi_intent_live.py tests/test_no_bundled_demo_key.py`
3. Frontend typechecks (both must exit 0):
   `cd frontend && npx tsc --noEmit` ; `cd src/frontend/admin-react && npx tsc --noEmit`
4. No credential in a built bundle:
   `cd frontend && npm run build && rg "local-merchant-key|local-owner-key" dist` → **must find nothing**.
5. **Known pre‑existing failures — do NOT report as new** (see `docs/KNOWN_TEST_FAILURES_2026-07-02.md`):
   `test_price_filter_nearest_viable_band...`, `test_negation_excludes_brand_end_to_end` (order‑flakes; pass
   in isolation), `test_selection_explanation_requests_llm_summary_and_trace` (narration/state),
   `test_observer_logs_for_recommend` (needs real observer/Redis). A regression = any NEW failure beyond these 4.

## PART 2 — Shopper clickthrough (5173). For each: do the steps, record PASS/PARTIAL/FAIL + evidence.

**T1 — Buyer debug tags hidden.** Search "gaming laptop under 1500". On the product cards, the "why" line
must show friendly text ("In stock", "Within budget") or nothing — NEVER `+in_stock`, `+ram_gb_min:8`,
`+embedding_similarity`. *If FAIL:* `frontend/src/components/ProductGrid.tsx` `cleanBuyerWhy` (~line 23).

**T2 — Cart failure is visible (not silent).** Find a product marked out of stock (or low stock) and click
Add; or add a bulk qty beyond stock. The chat must show a clear message ("out of stock or the quantity
exceeds what's available…"), NOT silence and NOT a false "added". *If FAIL:* `frontend/src/App.tsx`
`addToCart` catch (~line 700); `frontend/src/lib/api.ts` `addCartItem` error (~line 297).

**T3 — Widen‑budget chip.** Search "work laptops under 40" (below the ~$59 catalog floor). A "Widen a
little / Widen more" chip must appear and, when clicked, continue the flow. *If FAIL:*
`src/app/routers/chat.py` widen block (~line 2146).

**T4 — Multi‑intent buyer card (headline).** Steps:
  1. Search "business laptop around 1300"; add one laptop to the cart (if it 409s, note T2 and continue —
     the planner falls back to the last shortlist).
  2. In chat send verbatim: *"nah too expensive, actually i need 15 instead. what headsets and hard drives
     for 1200 for those?"*
  3. Expect a **MultiIntentCard** in the right panel: "Change [laptop] quantity to **15**" with a
     [Confirm qty] button; a **Headsets** and a **Hard drives** section each listing picks **≤ $1200** with
     [Add] buttons; a green "value" reframe note. Click [Confirm qty] → the cart line becomes 15. Click an
     [Add] → the accessory joins the cart. Nothing auto‑applies.
  *If FAIL:* is the flag ON (Part 0)? `frontend/src/components/MultiIntentCard.tsx`;
  `src/app/services/multi_intent_live.py`; `src/app/routers/chat.py` `multi_intent` block.

**T5 — Real clickstream (Track 2b).** Open the shopper with `?utm_source=google&utm_medium=cpc` in the URL,
then add a product to the cart. This emits a real `page_view` + `checkout`. (Verify the effect in admin T9.)
*If FAIL:* `frontend/src/lib/api.ts` `emitPageView`/`emitConsumerSignal`; `frontend/src/App.tsx` mount effect
+ `addToCart`; backend `POST /api/v1/consumer/ingest`.

**T6 — Decision Trace: procurement badge + live stream.** Run a bulk/procurement query (e.g. "40 business
laptops"), confirm the sourcing card (GATE 1), then open the Decision Trace for that turn. The **Procurement
tab shows a green ●**, and the trace streams without a dead panel (WS → SSE → poll degrades quietly; a WS
console warning is acceptable, a permanently blank trace is not). *If FAIL:*
`frontend/src/components/DecisionTrace.tsx` (streaming ladder ~line 519; badge ~line 1293);
`frontend/src/components/FulfilmentTraceLink.tsx`; `GET /api/v1/fulfillment/cases/by-trace/{trace}`.

## PART 3 — Admin clickthrough (3001).

**T7 — No pre‑auth 401 storm.** Open the admin app in a fresh tab with DevTools→Network open BEFORE
setting a key. You should see "Authenticating…" and at most one `/admin/me` 401 — NOT a burst of 401s
across every panel, and no empty cards. Then set the owner key → panels load. *If FAIL:*
`src/frontend/admin-react/src/App.tsx` panel gate (~line 276).

**T8 — Support‑response lane (M5).** Go to Market Intelligence. A "Support response lane" card must show an
objection theme → response angle (price → **value**) → guidance. *If FAIL:*
`src/frontend/admin-react/src/components/MarketIntelligence.tsx` (~line 267);
`GET /api/v1/fulfillment/market/support-response`.

**T9 — Marketing‑BI reflects real clicks (pairs with T5).** In Market Intelligence, open the traffic /
channel breakdown. After doing T5, the `google/cpc` channel's visits (and, after the add, conversions)
should be higher than the pure seed. *If FAIL:* `GET /api/v1/fulfillment/market/traffic-sources`;
`src/app/services/traffic_source.py`.

**T10 — Synthetic replay produces findings incl. the catalog gap.** Enable demo mode
(`FULFILLMENT_DEMO_ENABLED=1`, already set), reset + advance the replay to day 7. The findings must include
**`inventory_demand_mismatch`** (this was silently missing before). *If FAIL:*
`src/app/services/market_replay.py` (relative `_DATES` + `uid_hash` on demand signals).

**T11 — Draft email / supplier packet (where procurement lands).** Open `http://localhost:3001/?tab=procurement`,
select a `QUOTE_DRAFTED` / `AWAITING_APPROVAL` case, and confirm the "Supplier email approval packet" renders
(this is the intended surface — supplier send stays sandbox).

## PART 4 — UI/UX assessment (both surfaces)
Rate professionalism for a pilot: visual hierarchy, the MultiIntentCard's clarity, cart qty×unit display,
empty/zero‑result/loading/auth states, mobile width, any raw tokens/jargon leaking to buyers, admin panel
consistency. Give each finding a severity + `file:line` where identifiable.

## PART 5 — Adversarial stress (the headline feature)
Try to break the multi‑intent planner with hostile/ambiguous turns and confirm it **degrades safely**
(asks to confirm / falls back — never silently changes qty or budget or drops the prior item):
  - "make it 500 instead" (qty sanity), "actually nvm" (no‑op), "15 laptops and 3000 headsets" (absurd qty),
  - "$1200 for the laptop not the accessories" (scope inversion), a non‑English or emoji‑laden turn,
  - "add 10 of everything under 5 dollars" (budget below floor).
Report where the deterministic guard (`src/app/services/scatter_gather_guard.py`) or confirmation gate held,
and any turn that produced a wrong plan without asking.

## PART 6 — Deliverables
1. **Delta table:** T1–T11 → PASS/PARTIAL/FAIL → evidence (screenshot ref or exact response/DOM/console).
2. **UI/UX findings:** ranked, severity + file:line.
3. **For every PARTIAL/FAIL:** the diagnosis + the concrete fix and wiring (which file, which function, what
   to change, and how it connects end‑to‑end).
4. **Detailed roadmap** — a prioritized table with, per item: *what · why · effort (hrs/days) · risk ·
   dependencies · needs‑secrets?* Group into: (a) demo‑polish (no secrets), (b) test hygiene (the 4 known
   failures — the 2 order‑flakes signal real cross‑test state leakage), (c) production hardening (auth keys
   fail‑closed is done; what else — rate‑limit, secrets manager, CSP, PII retention), (d) real connectors
   (SMTP via Gmail App Password, IMAP/Gmail, catalog/inventory, SSO, payments — all gated on secrets/vendor
   accounts), (e) autonomy Phases 4–5 (gated on a–d + governance). Call out the single highest‑leverage next
   step for (i) a compelling pilot demo and (ii) a real production pilot.
