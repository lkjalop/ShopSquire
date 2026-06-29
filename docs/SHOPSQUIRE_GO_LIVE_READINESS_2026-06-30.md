# ShopSquire — Go-Live Readiness Breakdown

**Date:** 2026-06-30
**Scope:** Everything between "demo-ready (backend + admin)" and "trustworthy in front of a real buyer / real supplier."
**Key finding:** the production-integration *code already exists* (SMTP transport, KYV onboarding, Stripe checkout) — go-live is mostly **secrets + verification + data + a staged autonomy rollout**, not large new builds.

Ownership legend: **[Claude]** = code I can do · **[You]** = secrets / infra / business decision / live verification · **[Both]** = code then live-verify together.

---

## 0. Readiness scorecard

| Area | State | Gate to go-live |
|---|---|---|
| Procurement engine (fluid→confirm→cases→amend/supersede→write-bus→margin→rate-limit) | ✅ built + tested | none (proven) |
| Two safety gates (cart-confirm GATE 1, human send GATE 2) | ✅ intact | none |
| Security ratchets (agnostic-core, no-silent-except, no-untimed-http) | ✅ green | keep green |
| Buyer frontend (chat → sourcing card → confirm) | ⚠️ code done, **unverified in browser** | **Track A** |
| Full test suite | ⚠️ focused 402 green; full run unconfirmed + known BAG fail | **Track A** |
| SMTP (real supplier email) | ⚠️ code exists, sandbox default, no creds | **Track B** |
| Payments (Stripe) | ⚠️ demo checkout; real path exists, no key | **Track B** |
| KYV supplier allowlist | ⚠️ demo `.example` vendors; onboarding fn exists | **Track B/C** |
| Catalog data (real retail prices) | ⚠️ margin computes; prices are demo | **Track C** |
| Autonomous send | ✅ correctly OFF | **Track D** (keep OFF until dry-run) |
| Ops/observability/compliance | ⚠️ partial (audit panel, 409 UI) | **Track E** |

---

## Track A — Verification & test confidence (do FIRST, mostly free)

### A1. Browser re-verify the buyer journey **[You, ~15 min]**
The single most important open check. The CORP fix (`82fccbc`) is in code but unconfirmed in a real browser.
- **Do:** restart the backend; open the storefront on `:5173`; send "I need 20 gaming laptops + 20 headsets, need it in one week, budget ~1900 each".
- **Acceptance:** a `/api/v1/chat/stream` (or `/chat/query`) request fires AND the assistant panel updates AND the **sourcing preview card** renders with a "Confirm sourcing from cart" button. Then click it → admin Procurement queue shows the grouped cases + a notification.
- **If it still fails:** capture the DevTools Network + Console — the remaining suspects are stale vite build (hard-refresh / rebuild) or the request still going to `:8080` while the backend wasn't restarted after the CORP fix.

### A2. One clean FULL pytest pass **[Claude, ~30–60 min]**
The `-q` background run buffered nothing and likely hit a wall-clock cap. Re-run capturing output, in chunks, so we get a real result.
- **Do:** `python -m pytest tests/ --timeout=180 -p no:cacheprovider --tb=short -rf | tee fullsuite.log` (or run by directory: `tests/services`, `tests/api`, `tests/integration`, `tests/acceptance` separately to bound time and isolate slow files).
- **Acceptance:** a captured summary line; triage every failure to either "pre-existing/unrelated" (e.g. the BAG one) or "fix it". Note any test >30s (slow-but-not-hung) so we know where the wall-clock goes.
- **Known item:** `test_product_item_contract` (BAG-358234F2 price 180 vs price_cents 17995) — pre-existing 5¢ rounding; see F1.

### A3. Live procurement journey end-to-end (API, with the flags ON) **[Both, ~30 min]**
Confirm the journey on a fresh DB with `FULFILLMENT_DEFER_TO_CART=1` and `COMMERCE_CATALOG_ENABLED=1`.
- **Acceptance:** preview → confirm-cart → grouped cases → margin-advice shows a real margin (not `insufficient_data`) → request-approval → human dispatch → demo supplier reply → quote validated → economics + margin healthy. (Most of this you already proved; re-confirm with margin live.)

---

## Track B — Production integrations & secrets (needs YOU; code is ready)

### B1. Real SMTP for supplier RFQ email **[You: creds · Claude: any glue]**
`SmtpTransport` exists (`services/fulfillment/transport.py`), flag-gated `FULFILLMENT_SUPPLIER_TRANSPORT=smtp`, builds RFC-822, sends via `smtplib.SMTP`. Untested against a real server.
- **Do:** set `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_SENDER`; set `FULFILLMENT_SUPPLIER_TRANSPORT=smtp`.
- **Acceptance:** a **human-approved** RFQ to a *controlled test inbox* arrives, correct subject/body, claim-safe (no price/PO), `Reply-To` correct. Idempotency-key dedupes a re-send.
- **Safety:** do this with autonomy OFF — only the human-send path exercises it first.

### B2. Live Stripe checkout **[You: key · Claude: verify gate]**
`payments.checkout_initiate` has the real Stripe path + a demo fallback (currently demo).
- **Do:** set a live `STRIPE_API_KEY` (sk_…); ensure `ALLOW_DEMO_CHECKOUT` is OFF in prod (it already hard-blocks demo in non-dev).
- **Acceptance:** a test-mode PaymentIntent is created; the webhook transitions pending→paid and links `stripe_intent_id` to the order; demo mode is refused in prod.

### B3. KYV vendor onboarding (real supplier allowlist) **[You: vendor data · Claude: onboarding script]**
`register_vendor` / `lookup_vendor_by_domain` exist; today the allowlist is demo `.example` vendors.
- **Do:** register the real approved suppliers (domain + verified `contact_email` + risk tier + KYV evidence). Replace the demo routed suppliers (`_ROUTED_DEMO_SUPPLIERS` in `supplier_catalog.py`) with real supplier coverage, OR keep them demo-only behind a flag.
- **Acceptance:** the draft resolves a REAL supplier contact from the allowlist (never buyer text); a non-allowlisted domain is rejected; the send-cage still resolves the recipient from KYV only.

### B4. Secrets & config audit **[Both, ~1 hr]**
- **Do:** verify the prod-critical env: `AUDIT_CHAIN_SECRET` (already fail-closed at startup), `OWNER_API_KEY`, JWT/cookie secrets, `SECURITY_*` headers, Redis URL, DB URL (Postgres, not sqlite), feature flags reviewed.
- **Acceptance:** startup fails closed on any missing prod secret; no demo/test defaults leak into prod.

---

## Track C — Data readiness

### C1. Real retail prices for active SKUs **[You/Claude, ~1 hr]**
Margin now computes from the product catalog price (Gap-1 fix), but the demo prices need real headroom over wholesale for credible discounts.
- **Do:** seed `price_book_entry` (canonical) and/or `products.price_cents` for the live SKUs; ensure each routed supplier's wholesale is below retail with a real margin.
- **Acceptance:** `/cases/{id}/margin-advice` returns `verdict: healthy` (not thin/below_floor) for the demo SKUs, with a sensible discount-to-buyer headroom.

### C2. Inventory truth **[Both]**
- **Do:** confirm `inventory_level` per (sku, location) reflects real stock; the shortfall that triggers sourcing is real, not seed noise (the "9 cases blocked / SKU-1" demo rows are gone under the fluid model).
- **Acceptance:** a buyer order for an in-stock qty does NOT create a sourcing case; a real shortfall does.

---

## Track D — Autonomy & safety rollout (staged, governed)

Per the autonomy ladder (`docs/SHOPSQUIRE_SELL_ENGINE_AND_AUTONOMY_LADDER_2026-06-29.md`): slide C→B only with audit.

### D1. Keep autonomous send OFF until a real dry-run **[You decide]**
- `FULFILLMENT_AUTONOMOUS_RFQ` stays OFF. Only flip after: B1 (real SMTP) proven on the human path, the completeness gate (deadline/MOQ/allowlist/claim-safe) verified live, and the kill-switch tested.
- **Acceptance:** an autonomous send dry-run to a test inbox escalates correctly on every failing guard (incomplete deadline, over value/qty cap, untrusted recipient, rate limit) and only auto-sends when ALL pass; `FULFILLMENT_AUTONOMOUS_KILL_SWITCH=1` halts it immediately.

### D2. Margin gate mode **[You decide]**
- `FULFILLMENT_MARGIN_GATE` = `warn` (default, informs the human) vs `block` (UI requires override). Decide the prod posture; `warn` is the safe default.

### D3. Confirm-cart rate limit **[Claude, tune]**
- `FULFILLMENT_CONFIRM_RATE_PER_MIN` (default 20) — confirm the prod value for your buyer volume.

---

## Track E — Ops, observability, compliance

### E1. Admin audit panel + 409-replay UI **[Claude, ~1–2 days]**
From the roadmap "remaining-for-prod". The autonomous-audit endpoint (`GET /fulfillment/autonomous/audit`) + notifications exist; the admin surfaces for the full audit trail + idempotency-replay review are partial.

### E2. Monitoring/alerting **[Both]**
- Health of: Redis, sync-worker, celery-worker, the supplier poller. Trace propagation end-to-end. Alert on: send failures, quarantines, escalation backlog, kill-switch state.

### E3. Compliance pass **[Claude/You]**
- The compliance master plan (`docs/COMPLIANCE-MASTER-ACTION-PLAN.md`) — PCI/MFA (`PCI #5 MFA pending`), the framework control matrix. Decide what's required for YOUR go-live scope (a B2B procurement pilot may not need full PCI if Stripe holds the card data).

---

## Track F — Known defects & polish

- **F1. BAG price↔price_cents** (`test_product_item_contract`): one accessory's upstream candidate data has `price` (whole-dollar) out of sync with `price_cents` by 5¢. Robust fix = reconcile `price` from `price_cents` at the product-source layer. Low risk, isolated; do as a focused change.
- **F2. Benign-image tone** — softened in code (`gap 5`); live-confirm a clean upload no longer shows "flagged by our security system."
- **F3. NL parsing breadth** — adjective tolerance added; consider number-words ("twenty laptops") and more connectors if buyers phrase orders loosely.
- **F4. Checkout→sourcing UX** — the bridge works + is timeout-bounded; consider a clearer "ship in-stock now / source the rest" split screen later.

---

## Recommended sequence (fastest path to a trustworthy pilot)

1. **A1 browser re-verify** (you, 15 min) — unblocks the whole frontend story.
2. **A2 full suite green** (me) — real confidence; triage failures.
3. **C1 real prices + C2 inventory truth** (us) — margin credibility + correct sourcing triggers.
4. **B1 SMTP on the human-send path** (you creds, me glue) — RFQ emails actually send, human-approved only.
5. **B3 KYV real suppliers** (you data) — real allowlist.
6. **D1 autonomous dry-run** (us) — only after 1–5; keep OFF until it passes.
7. **B2 Stripe + B4 secrets + E1/E2 ops** — in parallel as your launch scope requires.

**Two go-live definitions:**
- **Pilot go-live (human-in-the-loop, real supplier, real buyer):** Tracks A + B1 + B3 + C. Autonomy OFF. Achievable quickly — it's mostly secrets + verify.
- **Full autonomous go-live:** add D1 (dry-run passed) + E (ops/compliance) + B2 (payments). The deliberate, audited end state.

**What needs YOU vs ME:** the remaining *code* is small (F1, E1, glue). The gating items are **your secrets (SMTP/Stripe/KYV), your data (prices/inventory/suppliers), and live verification** — none of which I can do without those inputs. Hand me any of the code items and I'll execute + test them.
