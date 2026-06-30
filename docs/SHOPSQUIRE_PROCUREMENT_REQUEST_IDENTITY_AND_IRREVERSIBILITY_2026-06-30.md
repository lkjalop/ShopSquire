# Procurement Request (PR) Identity, Lifecycle & Irreversibility Ladder

**Status:** design + roadmap (2026-06-30). Supersedes the ad-hoc `order_group_id = cart-${uid}` fix (R1), which
was too coarse a grain. Agnostic-core throughout: PRs are opaque ids + cents + states; no product vocabulary.

## 1. Problem

A buyer changes their mind repeatedly. Today the order key was either the per-turn trace id (→ every amend
spawns a NEW case = churn/duplication) or the session uid (→ a *new* unrelated order collides with a still-open
prior order = cross-order contamination, R1). Neither models "one order that I amend until I place it, then a
fresh order next time." And nothing models what happens after money + a supplier commitment are real.

## 2. The Procurement Request (PR) — stable identity + naming convention

Anchor every order to a **Procurement Request**, minted ONCE when sourcing intent crystallises, stable across
all amendments, rotated only on a lifecycle event. The gist/summary is a *derived label*, never the key (the
gist mutates when you amend; the identity must not).

```
PR    Procurement Request   PR-{tenant}-{YYYYMMDD}-{shortid}   ← THE anchor + single source of truth
 └─ amendment v1, v2 …      PR-…#v{n}                          ← every mind-change = append-only version
     └─ CASE per supplier   CASE-{PR}-{group}                  ← re-materialised per amendment; old → SUPERSEDED
         └─ PO              PO-{PR}-{seq}                       ← minted at GATE 1 (cart confirm)
             ├─ GR          GR-{PO}                            ← goods receipt (built: record-receipt)
             └─ INV         INV-{PO}                           ← invoice (built: record-invoice → 3-way match)
```

Maps onto existing code: `order_group_id` → PR id; bitemporal case versions → amendments; PO finalization →
PO; record-receipt/invoice → GR/INV. This NAMES and STABILISES what already exists.

## 3. Lifecycle & rotation policy (fixes R1 structurally)

PR minted at cart-open (first sourcing preview), **server-persisted** (not just sessionStorage), bound to the
authenticated buyer. Rotation = `should_rotate(...)`:
- **Explicit** "new order" / cart-clear (primary signal) → rotate.
- **Auto on finalize**: once an order is placed (PO issued + buyer done) the NEXT sourcing mints a fresh PR.
- **Idle-TTL safety net** (default 24h): a stale cart can't capture an unrelated future order.
- Amendments between confirm and send **do NOT rotate** — they supersede within the PR.

## 4. Retention & single source of truth

Retention tied to the irreversibility boundary, not a flat timer:
- **Pre-Gate-1 (fluid preview):** EPHEMERAL — short TTL (session/Redis, minutes–hours). A discarded mind-change
  evaporates cheaply; no external commitment exists.
- **Post-Gate-1 (PR materialised):** DURABLE append-only bitemporal — nothing hard-deleted; superseded versions
  stay readable (`valid_to` stamped, SUPERSEDED version inserted). Retain for the compliance window
  (procurement/financial → 7 years). **SSOT = the PR's bitemporal version chain** (`version_asof`).

## 5. The irreversibility ladder (the "what then?" answer)

**Principle: supersede/redraft applies only before irreversibility. After money + a supplier commitment are
real, a mind-change is a NEW governed transaction, and the original committed order stands.**

| Gate | State (fulfillment) + payment | Mind-change handling | Authority |
|---|---|---|---|
| 0 | pre-confirm preview | free redraft | agent |
| 1 | cart confirmed, PO drafted, not sent | **supersede** (re-materialise PR) | agent; buyer confirms |
| 2 | RFQ **sent** (QUOTE_SENT+) | operator-routed supersede + `void_hash` + `cancellation_advised` | human operator |
| 3 | **buyer paid AND supplier PO accepted** | **change-order OR cancellation**, economics surfaced, original stands, new intent = `derived_from` PR | human only; agent may PROPOSE, never execute money movement |

At Gate 3 the platform must NOT silently supersede. It must:
1. Hard-stop auto-supersede (already operator-gated post-send; add a distinct post-PAYMENT guard).
2. **Surface the economics** (reuse the margin engine pointed at the cancellation): restocking cost, supplier
   change/cancel fee, extra stock carried, re-sourcing cost for the new intent.
3. Open a **human-mediated change/cancellation flow** (the escalation room) with explicit options:
   amend supplier PO (change order, may carry a fee) · cancel + restock + refund (fee per policy) · fulfil
   original + open a NEW PR for the new intent.
4. Keep the original PR standing; link the new intent as a separate PR `derived_from: PR-original`.

## 6. Fraud / attack vectors & defenses

| Vector | Defense |
|---|---|
| **Fraudulent-return / mind-change abuse** (pay → cancel after supplier commit to extract refund, keep value) | Gate-3 human gate; cancellation/restock **fee policy** (ceilinged); **fraud scoring** on amendment+cancellation patterns; hold/escrow until fulfilment; original order stands |
| **Amendment-churn DoS** (rapid amends thrash sourcing, spam suppliers with redrafts) | Per-PR **amendment cap** + rate-limit (`FULFILLMENT_CONFIRM_RATE_PER_MIN` exists); nothing external pre-confirm; debounce redraft |
| **Cross-order contamination / replay** | PR bound to authenticated buyer + idempotency probe + PR rotation |
| **Late supplier quote on a voided draft** | `void_content_hash` quarantine (built) |
| **Repudiation** ("I didn't approve that") | Per-user identity (#4) stamped on every transition |

## 7. Agent governance bounds (bounded autonomy per gate)

- Gate 0: agent redrafts freely, nothing external.
- Gate 1: agent materialises PR + drafts; **human confirms cart**.
- Gate 2: **human-only send** (or flag-gated SAFE-FIRST autonomous send within KYV + allowlist + rate/value caps).
- Gate 2→3 amend after send: agent may **not** auto-supersede; operator-routed.
- Gate 3: agent may **PROPOSE** a change-order/cancellation with economics; a **human authorizes** any money
  movement/cancellation. The agent never autonomously refunds, cancels a paid order, or absorbs a loss.

Enforced via `adaptive_action_gate` + approval tiers + the escalation room.

## 8. Agnostic-core extraction plan

New/changed core modules (vertical-blind — opaque ids/cents/states, graduate into `_CORE_MODULES`):
- `procurement_request.py` — PR id minting + naming hierarchy + rotation policy + amendment-seq. **(this PR)**
- `domain.py` — Gate-3 states + change-order/cancellation transitions (actor-guarded: agent-propose, human-execute).
- `cancellation_economics.py` (planned) — restock/fee/penalty math over cents (reuses economics).
- `procurement_fraud_signals.py` (planned) — amendment/cancellation pattern signals (counts, no product vocab).

## 9. Reordered roadmap

- **Pass A — PR identity foundation** *(in progress)*: `procurement_request.py` (mint/name/rotate, agnostic, tested)
  → then wire: mint on first preview, server-persist, `should_rotate`, replace `cart-${uid}` (closes R1 properly).
- **Pass B — stop losing data (parse spine)**: L5/L6/D1 — surface unresolved phrases, sum-on-collision, no
  multiline collapse; tests prove no line/qty dropped.
- **Pass C — irreversibility ladder (Gate 3)**: domain states + change-order/cancellation flow + economics
  surfacing + `derived_from` linkage + human gate. Production-grade; refund/restock external calls stubbed
  behind flags until payment/ERP secrets land.
- **Pass D — fraud + governance**: per-PR amendment caps + rate-limit + cancellation-pattern fraud signals +
  agent-cannot-execute-money tests.
- **Pass E — #4 identity** (named approvals/SoD), **#5 amend-diff** (supersedes_case_id + by-order endpoint),
  **#2 KYV dedup**, then secrets-gated #3 send / #8 inbound.

## 10. Test strategy

- **Data integrity:** no line/qty loss (parse golden cases); idempotent double-confirm; **no cross-order
  contamination** (PR rotation property test); append-only preservation; post-send + post-payment refusal.
- **Fraud:** amendment-churn rate-limit; cancellation-abuse pattern flagged; replay rejected.
- **Governance:** agent CANNOT fire Gate-3 money actions (actor-guard test); human-only gates hold.
- **State machine:** the full ladder transitions + actor guards; `derived_from` linkage.
- **Ratchets:** `test_no_flavour_in_core`, `test_no_silent_except_in_core` stay green.
