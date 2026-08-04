# ShopSquire — Commerce-Integrity Security: Upsell Poisoning, Coupon Attacks, Observer (2026-06-18)

Scope: data-poisoning of the upsell/recommendation signals, coupon/voucher attacks, how
`recommend.py` participates, and what the **Security_Observer_Agent** must monitor + how to wire
it. Grounded in code (file:line), verified — not theoretical.

Tie to architecture: upsell signals (co-purchase, clicks/hovers, sales velocity) are
**`external_analytical`** provenance per `SHOPSQUIRE_ROADMAP_CANONICAL_2026-06-18.md` — poisonable,
advisory-only. They may move ranking but must **never gate a consequential action**, and they must
be **poison-screened before use**. This doc is the security spec for that tier.

---

## 1. What's already defended (credit where due)

| Control | Where | Verdict |
|---|---|---|
| Prompt-injection in product name/SKU | `checkout_upsell._SUSPICIOUS_NAME_PAT` ([:20](src/app/services/checkout_upsell.py#L20)), checked in `_looks_poisoned` ([:416](src/app/services/checkout_upsell.py#L416)) | ✅ good — blocks "ignore previous", `<script`, `drop table` in catalog text |
| CTR-spike interaction poisoning | `_looks_poisoned` ([:418-422](src/app/services/checkout_upsell.py#L418)): hovers≥30 ∧ ctr≥0.95 ∧ sales=0 → `interaction_poisoning_ctr_spike` | ✅ real, but **evadable** (keep hovers<30 or ctr<0.95, spread across SKUs) |
| Interaction-write authz | `POST /recommend/interaction` requires `MERCHANT/OWNER/DEVELOPER` ([recommend.py:14270](src/app/routers/recommend.py#L14270)); context `security_sanitize`d; uid hashed | ✅ not anonymous |
| Voucher race / max-uses | atomic conditional `UPDATE … WHERE use_count < max_uses` + rowcount rollback ([cart.py:563-573](src/app/routers/cart.py#L563)) | ✅ **race-safe even if Redis lock is down** — the DB does the real work |
| Voucher replay / stacking | binding INSERT raises on dup; "one voucher per cart" ([cart.py:535-561](src/app/routers/cart.py#L535)); `UNIQUE(cart_id,voucher_id)` | ✅ solid |
| Voucher expiry / active / negative-price | expiry ([:518](src/app/routers/cart.py#L518)), active ([:514](src/app/routers/cart.py#L514)), discount clamped `max(0, subtotal-discount)` ([:636](src/app/routers/cart.py#L636)) | ✅ no negative total |

**This is a security-aware codebase.** The gaps below are about *coverage* and *observability*,
not a missing foundation.

---

## 2. Confirmed bugs / gaps (ranked)

| # | Sev | File:line | Gap | Attack | Fix |
|---|---|---|---|---|---|
| **B1** | High | [cart.py:497](src/app/routers/cart.py#L497) | `min_order_cents` is SELECTed but **never enforced** | Apply a "$500-min, $50-off" voucher to a $1 cart → margin leak / free-money | Enforce: reject if `cart_subtotal_cents < min_order_cents` before binding |
| **B2** | High | [cart.py:497](src/app/routers/cart.py#L497) | `applies_to_skus` SELECTed but **never enforced** | SKU-restricted voucher (e.g. clearance-only) applied to any cart | Enforce: voucher valid only if cart ∩ applies_to_skus ≠ ∅ |
| **B3** | High | [checkout_upsell.py:794,1081](src/app/services/checkout_upsell.py#L794) | Poison guard **emits no security event** — filters silently | Co-purchase / CTR poisoning is invisible to the SOC; no incident, no trend, no block-rate metric | Emit `commerce_poison_detected` to decision_log + observer with sku, reason, factors |
| **B4** | High | `security/observer.py` | Observer has **zero commerce-integrity signals** (watches only LLM/content: jailbreak/PII/QR) | Economic attacks (poisoning, coupon abuse, discount manipulation) bypass the SOC entirely | Add a `commerce_integrity` detector class (§4) |
| **B5** | Med | [cart.py:577-578](src/app/routers/cart.py#L577) | `db.commit()` wrapped in `except: pass` | Commit fails → caller told voucher applied, DB rolled back → inconsistent state, silent | Log+raise on commit failure (one of the 4,393 silent handlers, on a money path) |
| **B6** | Med | [recommend.py:14266](src/app/routers/recommend.py#L14266) | No rate-limit on interaction writes (only role gate) | A leaked/shared merchant key can mass-inject interactions under the CTR threshold | Per-uid_hash velocity cap + emit on breach (feeds B4) |
| **B7** | Low | `_looks_poisoned` CTR rule | Single-threshold, evadable; no cross-SKU / cross-uid view | Distributed low-and-slow poisoning | Move detection to the observer where it sees aggregate velocity, not per-call |

---

## 3. The attack surface, concretely

### 3a. Upsell / recommendation data poisoning
The upsell score blends `co_purchase` (order history), `recent/prior_sales` (velocity), and
`interactions` (click/hover/atc) — all **`external_analytical`**, all attacker-influenceable:

- **Co-purchase poisoning** ([_copurchase_scores:383](src/app/services/checkout_upsell.py#L383)): craft orders pairing a *target* SKU with a *malicious/high-margin/OOS-dropship* SKU to force it into "frequently bought together." Requires order-creation ability; gate: order auth + the poison guard, but the guard checks CTR, **not** co-purchase anomaly.
- **Interaction inflation** ([:712](src/app/services/checkout_upsell.py#L712)): pump clicks/atc to raise `intent`. CTR guard catches the blatant case; low-and-slow evades it.
- **Velocity/trend gaming** ([:664](src/app/services/checkout_upsell.py#L664)): `recent/prior` ratio (`trend`) — fake recent sales to look "trending."
- **Catalog-text injection**: defended by `_SUSPICIOUS_NAME_PAT` ✅.

**Architectural fix (the real one):** treat these signals as `external_analytical` — they rank,
never gate; and they pass through a **poison screen that emits to the observer**, so detection is
aggregate (cross-SKU/cross-uid velocity at the SOC), not a single evadable per-call threshold.

### 3b. Coupon / voucher attacks
Endpoint `POST /cart/voucher` ([:596](src/app/routers/cart.py#L596)), feature-flagged off by
default, role-gated. Strong on race/replay/stacking/expiry/negative-price. **Weak on**
*eligibility* (B1 min_order, B2 applies_to_skus) and *observability* (no abuse signal). Residual:
- **Eligibility bypass** (B1/B2) — the live ones; fix first.
- **Enumeration / brute-force**: codes are guessable if short; role gate + (recommended) per-uid
  velocity cap + emit on repeated `voucher_not_found` (reconnaissance signal).
- **Exhaustion griefing**: hammer a public code to burn `max_uses` against legit buyers →
  observer should flag `voucher_exhaustion_velocity`.

### 3c. recommend.py's role
`recommend.py` is three things in this story: (1) it **hosts the poisoning entry point**
(`/interaction`); (2) it **surfaces poisoned output** (calls `checkout_upsell` and renders upsell
to the buyer); (3) it runs the **early security gates** — but those gates are **content/LLM
threats** (prompt-injection, QR, PII), *not* commerce-integrity. So a poisoned co-purchase signal
sails through every existing gate. The fix is not more gates in recommend.py — it's emitting
commerce events to the observer and letting the observer own aggregate detection.

---

## 4. What the Security_Observer_Agent must add

Today `observer._detect_signals` ([:93](src/app/security/observer.py#L93)) covers jailbreak,
PII/PCI, api_key, prompt_injection, data_exfiltration, training_poisoning, model_drift, OCR/QR —
mapped to MITRE ATLAS + OWASP LLM. **Add a parallel `commerce_integrity` signal class:**

| Signal | Trigger | Source event | MITRE/OWASP-ish tag |
|---|---|---|---|
| `interaction_poisoning` | per-uid_hash interaction velocity ≫ baseline; CTR spike with zero conversion | `/interaction` write + poison guard | ATLAS AML.T0020 (data poisoning) |
| `copurchase_poisoning` | a co-purchase pair appears with anomalous velocity / from few uids | poison guard on the co-purchase path | ATLAS data poisoning |
| `voucher_abuse` | repeated `voucher_not_found` (enumeration), `voucher_exhausted` velocity, per-uid redemption velocity | voucher endpoint failures | OWASP API4 (resource), business-logic abuse |
| `discount_policy_violation` | applied voucher whose min_order/applies_to_skus would have failed (post-B1/B2 these become hard blocks + an event) | voucher endpoint | business-logic abuse |
| `price_integrity_anomaly` | upsell/checkout price deviates from catalog band (`product_classifier.price_anomaly`) | finalizer / upsell | tampering |

Key principle: detection lives at the **observer** (it sees aggregate, cross-entity velocity),
not in per-request guards (which see one call and are evadable). Per-request guards **emit**;
the observer **correlates + decides** (and can raise an incident via the existing escalation path).

---

## 5. Wiring (minimal, follows existing patterns)

1. **Emit from the guards.** In `checkout_upsell` where `_looks_poisoned` fires
   ([:794](src/app/services/checkout_upsell.py#L794), [:1081](src/app/services/checkout_upsell.py#L1081)) and
   in the voucher endpoint on each rejection, call the existing `decision_log.log_trace_event`
   (already imported across the codebase) with `event_type="commerce_integrity"`, a `signal`
   name, and the entities (sku/code/uid_hash/factors). No new infra.
2. **Observer consumes** those events: extend `_detect_signals` with the `commerce_integrity`
   class; add the velocity baselines (Redis counters keyed by uid_hash/sku/code, the same shape as
   existing rate logic).
3. **Bounded autonomy tie-in:** a `commerce_integrity` incident above threshold routes the
   affected action (e.g., auto-applied discount, dropship reorder triggered by a "trending" SKU)
   to human review via `policy/execution_gate.decide()` — because the triggering evidence is
   `external_analytical`/poisoned, it must not auto-execute (the provenance→autonomy rule).
4. **Metrics:** add `commerce_poison_blocked_total` and `voucher_abuse_total` counters so silent
   filtering becomes a dashboard number (mirrors the `partial_failure` work in the deep-dive §7).

---

## 6. Recommended fix order (contained, money-path-aware)

Because B1/B2/B5 touch the money path, they get tests + review, not a drive-by:

1. **B1 + B2** (voucher eligibility) — enforce `min_order_cents` and `applies_to_skus` before
   binding; unit tests for below-min and wrong-SKU rejection. *(small, high-value, money-correctness)*
2. **B3** (poison guard emits) — wire `log_trace_event("commerce_integrity", …)` at the two
   `_looks_poisoned` sites + a counter. *(observability, no behaviour change to buyers)*
3. **B5** (commit silent-fail) — log+raise on voucher commit failure. *(contained)*
4. **B4 + B6 + B7** (observer commerce class + interaction velocity) — the real defensive win;
   sits in Phase 2.5/3 alongside the provenance-tier work, because it depends on the
   `external_analytical` screening contract.

B1/B2/B3/B5 are a clean next PR (all in `cart.py`/`checkout_upsell.py`, all tested). B4/B6/B7 are
an observer feature that should land with the provenance model so detection and tiering ship
together rather than bolted on.
