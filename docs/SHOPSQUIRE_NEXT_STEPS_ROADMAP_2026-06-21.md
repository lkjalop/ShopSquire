# ShopSquire — Comprehensive Next-Steps Roadmap (2026-06-21)

Grounded follow-up to the 7-track agnostic/latency/security work (commits `7aa8d54`→`13c1b37`).
Every claim below was verified against the live code; where an earlier audit was wrong, it is
corrected here so we don't "fix" things that already work.

## 0. The unifying theme — *signal drop*

The backend computes rich, defensible signals and then **drops them** before they reach the route
response, the UI, or sibling agents. This one pattern explains the bloated route, the "hollow"
ranking, and the low-trust UI. Every workstream below is, at heart, *surfacing intelligence we
already compute*.

| Signal | Produced at | Dropped before |
|---|---|---|
| Per-item stock / OOS | `recommend.py` stock penalty (~L10773) | `Product` type ([App.tsx:25](../frontend/src/App.tsx#L25)) has no stock field |
| "not sold by this store" | external research SKU-gate | UI never renders it |
| Image security (steg/QR/adversarial) | `cv_tier2_pipeline.py` | Buried in collapsible trace; Security_Observer doesn't ingest it |
| Contrastive "why #1 beats #2" | not produced | ranking emits templated `why` only |
| PAN in payloads | — | **not masked by `scrub_pii`** (PCI gap, see §3) |

---

## 1. Verified findings vs the earlier audit (corrections)

| Earlier claim | Verified reality | Action |
|---|---|---|
| "Idempotency needs Redis SETNX" | DB `ON CONFLICT DO NOTHING` is already atomic cross-replica ([payments.py:64](../src/app/routers/payments.py#L64)). The real defect is the **fail-OPEN fallback** ([L83](../src/app/routers/payments.py#L83)) | Make payments idempotency **fail-closed**, not Redis |
| "Flip PCI boundary default 0→1" | Already defaults **on** in production ([pci_boundary.py:22](../src/app/security/pci_boundary.py#L22)); off in non-prod by design | No change needed |
| "Refunds bypass the gate" | `refund_requested` **is** enforced via `enforce_action_authority("refund")` ([events.py:70](../src/app/routers/events.py#L70)), which raises 403 on deny | Lower priority: migrate to `execution_gate.decide()` for the unified `policy_evaluation_log` guarantee (strangler) |
| "Traces capture card data" | Traces **do** scrub via `redact_for_trace`→`scrub_pii` ([deps.py:230](../src/app/deps.py#L230)) | But `scrub_pii` does **not** mask PAN — real gap (§3) |
| "execution_gate is the gate" | `decide()` is canonical but **only `supplier_communication` calls it** live | Wire more consequential actions over time |

---

## 2. Workstream A — Surface dropped signals on results (UX #1, highest trust ROI)

**What goes where:** purely additive. ProductGrid already renders `why` ([ProductGrid.tsx:39](../frontend/src/components/ProductGrid.tsx#L39)); it lacks stock + seller badges.

**Wiring:**
1. Backend (small): in the main results assembly, expose per-item `in_stock: bool` and `stock_status: "in"|"low"|"out"|"unknown"` on each result dict (the fast path already bakes `"in_stock"` into `features` at [recommend.py:969](../src/app/routers/recommend.py#L969); lift it to a first-class field on both paths). Expose `sold_here: bool` for external-research items (already `sku=None` → un-cartable).
2. Frontend: extend `Product` type ([App.tsx:25](../frontend/src/App.tsx#L25)) with `in_stock?`, `stock_status?`, `sold_here?`; render badges + disable "Add to Cart" when `out`.

**Tests:** `frontend` uses **vitest** (`frontend/package.json`). Add `ProductGrid.test.tsx`: renders an OOS product → shows "Out of stock" + disabled add; renders `sold_here:false` → shows "not sold by this store". Backend: extend the contract test to assert results carry `stock_status`.

**Effort:** ~2 days. **Risk:** low (additive).

---

## 3. Workstream B — PCI-DSS guards (to CORE) ⭐ executing first

These are vertical-blind, cross-tenant guards → they belong in **core** (`deps.py`, `security/`,
`policy/`), never in a StoreProfile adapter.

### B1 — PAN/card masking in `scrub_pii` (CORE, P0, executing now)
`scrub_pii` ([deps.py:137](../src/app/deps.py#L137)) masks email/phone/SSN/IP/API-key but **not card
numbers**. Because it is the choke point for both `redact_for_trace` (every decision-trace write) and
`security_sanitize` (LLM-bound payloads), a pasted PAN can currently land in a trace/log/prompt.
**Fix:** add a card-masking step reusing `security/pci.py`'s `CARD_RE` + `luhn_check` (mask a 13–19
digit run only when it passes Luhn OR has card/cvv/expiry context — mirrors `contains_pci_data`, so
SKUs/model numbers are not over-redacted). Req 3/4.
**Test:** `4111 1111 1111 1111` → `[REDACTED_CARD]` in `scrub_pii`, `security_sanitize`,
`redact_for_trace`; CVV-with-hint masked; a 16-digit SKU / "Inspiron 14 7440" left intact.

### B2 — Payments idempotency fail-closed (P1)
[payments.py:83](../src/app/routers/payments.py#L83) returns `True` (allow) on DB error → double-charge
window. Make the payments path fail-**closed** (treat as duplicate / 503) while leaving non-payment
event idempotency as-is. Req 6.2. Test: simulate DB error → request rejected, not allowed.

### B3 — Script integrity on server-rendered checkout (P2, Req 6.4.3 / 11.6.1)
[ui_storefront.py](../src/app/routers/ui_storefront.py) server-renders checkout HTML and loads
`js.stripe.com`. Add a tight per-page CSP + Subresource Integrity on the Stripe tag + a script
inventory note. This is the e-skimming control most teams miss.

### B4 — (later) Migrate refund/discount to `execution_gate.decide()` (Req 10 audit guarantee)
Refunds are enforced but the unified "every consequential action writes `policy_evaluation_log`"
guarantee only fires through `decide()`. Strangler-migrate `events.refund_requested` +
`bundle_approvals` once a verdict-enforcement helper exists. Medium risk (legacy path has ~9 callers).

**Claim discipline:** keep saying "tokenized, no cardholder data stored" — never "PCI compliant"
without QSA validation. Existing `docs/COMPLIANCE-FRAMEWORK-CONTROL-MATRIX.md` already says this.

---

## 4. Workstream C — Agents

### C1 — Security_Observer ingests CV adversarial signals (the "security observer" gap)
[security/observer.py](../src/app/security/observer.py) is real (40+ regex detectors) but **does not
read the `cv_tier2_pipeline` steg/QR/adversarial findings** — another signal drop. Wire the CV
verdict into the observer's event stream so an adversarial image raises a security event (not just a
UI badge). High value, fits the security positioning. Medium effort.

### C2 — Product_Ranking contrastive `why` (quick visible win)
[product_ranking_agent.py:~347](../src/app/services/product_ranking_agent.py#L347) emits a templated
reason per product. Add ONE cached LLM call over the top-3 to produce "ranks above #2 because
{specific spec}". Cache by result fingerprint (no latency hit). ~2 days.

### C3 — Product_Identity → retrieval constraints (strategic multimodal fix)
[product_identity_agent.py](../src/app/services/product_identity_agent.py) is real + now
timeout-hardened, but its output never becomes retrieval constraints (the multimodal anchoring bug).
Inject identified brand/specs as soft constraints before candidate retrieval. ~1 sprint.

**Ranking of need:** Product_Ranking (cheap, visible) → Security_Observer CV wiring (security
differentiator) → Product_Identity steering (multimodal) → Fraud_Scorer (static weights, no feedback
loop) → Inventory_Agent (rules-only, no forecasting).

---

## 5. Workstream D — Shrink `recommend.py`

`suggest()` is **7,627 lines** ([L4059](../src/app/routers/recommend.py#L4059)) — 62% of the file;
the other 116 helpers are fine. Safety net already built: `SuggestContext`, `ctx_access_map.py`,
golden contract, both ratchets. Extraction order (one per commit, contract-gated):

1. **Narration cluster** (~477 lines, scoped) → unlocks the async narration already built. Low risk.
2. **Fast-path catalog** ([L896](../src/app/routers/recommend.py#L896)) → `recommend_fast_path` service. Low.
3. **Image/CV stage** → one `image_stage(ctx)`. Medium.
4. **Ranking + answer assembly** ([L3359](../src/app/routers/recommend.py#L3359)). Medium-high.
5. **Action/policy + inventory annotation** → leaves `suggest()` as orchestration only.

Target: a ~1.5–2.5k-line route + a dozen stage services, which then lets the Orchestrator (currently
a decision-gate that *logs* agent names but invokes them from the route) become a real agent bus.

---

## 6. Sequenced plan

| # | Item | Effort | Risk | Why this order |
|---|---|---|---|---|
| 1 | **B1 PAN redaction (core)** | hours | low | P0, money-path, testable, executing now |
| 2 | A results-card signals | ~2d | low | highest trust ROI |
| 3 | C2 ranking contrastive `why` | ~2d | low | visible quality |
| 4 | B2 idempotency fail-closed | hours | low | money-path safety |
| 5 | C1 Security_Observer CV wiring | ~3d | med | security differentiator |
| 6 | D1 narration extraction | ~1 sprint | med | first monolith chunk |
| 7 | C3 identity→constraints | ~1 sprint | med | multimodal anchoring |
| 8 | B3 checkout CSP/SRI | ~2d | low | e-skimming control |
| 9 | B4 refund→decide() migration | ~1 sprint | med-high | Req-10 audit unification |

Honest framing (matches the Sierra comparison): this is an **applied-research platform with working
bounded-autonomy primitives**, not yet production-grade. The fastest path to a credible demo +
commercial trajectory is *surfacing the intelligence already computed* (items 1–4), not new models.
