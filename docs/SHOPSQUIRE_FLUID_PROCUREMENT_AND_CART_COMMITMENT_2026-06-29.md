# ShopSquire — Fluid Procurement & the Cart-Commitment Boundary

**Date:** 2026-06-29
**Status:** Design proposal (pre-build) — supersedes the ad-hoc "buyer_amended_product transition" idea.
**Author:** Claude Code session (architecture rethink with the platform owner).

---

## 0. The one-sentence reframe

> The supplier RFQ draft is **fluid** — it re-resolves the SKU, re-routes to the correct
> supplier, and redrafts every time the buyer changes their mind — and **nothing external
> happens until the buyer confirms the shopping cart.** Cart-confirmation is the single
> commitment boundary that locks the purchase order and fires the third-party supplier reorder.

Everything below follows from that boundary.

---

## 1. Why the cart-confirmation boundary is the right design

The earlier idea (a `buyer_amended_product` state transition on an already-open case) treated
every mind-change as a mutation of a durable record. That creates orphaned cases, churn in the
audit trail, and a hard "what if the RFQ already went out" problem on every edit.

Moving the commitment boundary to **cart-confirm** makes the hard problems disappear for the
common case:

| Concern | Before (per-change case mutation) | After (fluid-until-cart-confirm) |
|---|---|---|
| Mind-change cost | Mutates a durable case + trace | Pure local recompute, zero external effect |
| Orphaned cases | One new case per follow-up | One fluid intent per cart; **case materializes at confirm** |
| Re-route surprise | Supplier silently changes | Re-route shown live as a *consequence* in the panel |
| Audit volume | A trace event per keystroke | Durable trace only post-confirm |
| "RFQ already sent" | Possible on any edit | Impossible before confirm (nothing is sent) |

**Key principle: pre-confirmation is ephemeral; post-confirmation is durable.**
Before cart-confirm, the buyer's intent lives in session/cart state (cheap, debounced, not
durably traced). At cart-confirm, a durable bitemporal procurement case is created — *that* is
the audit artifact.

---

## 2. The two gates, re-anchored

- **GATE 1 — Buyer commitment = Cart confirmation.** The buyer clicking "Confirm order" in the
  cart is the commitment. This replaces the abstract `buyer_committed` event with a concrete,
  legible UI action. Until this point: no case is durable, no supplier is contacted.
- **GATE 2 — Human send (or bounded autonomy).** After confirm, the materialized RFQ either
  waits at `AWAITING_APPROVAL` for a human (default) or auto-sends under the existing
  flag-gated autonomous-send path (after-hours hands-off). Unchanged from today, just downstream
  of the new GATE 1.

The human admin can **jump in or out at any point before the irreversible boundary** (the
actual supplier send / PO issue). Taking over and releasing a case are both trace events
(actor = human), so the bitemporal record always shows who acted.

---

## 3. The draft is a projection, not a stored-per-change artifact

The RFQ draft is a **pure function** of `(committed cart state, supplier routing rules)`:

```
cart line items ──► resolve SKUs ──► plan supplier split ──► per-supplier RFQ draft
     (fluid)          (deterministic)     (order_split)        (build_draft, pure)
```

Implications:
- **Do not persist a draft on every change.** Recompute lazily (on cart-confirm, or on-demand
  when an operator opens the case to preview).
- **Persist exactly one immutable draft: the one that is actually sent.** That hash-pinned
  artifact is what audit and the supersession protocol reference.
- Supplier routing is already deterministic by SKU (`supplier_catalog._supplier_route_for_product`),
  so "re-route on item change" is free — it falls out of recomputing the projection.

---

## 4. Mind-changes, reverting, and going back — without blowing up data

The buyer will flip between ideas, go back, revert to an older choice. Handling that bitemporally
without unbounded growth or an attack surface:

1. **Bitemporal the cart, not the keystroke.** Cart line-items carry `valid_from / valid_to`.
   A confirmed change is a new version. Pre-confirm browsing churn is session state, not a
   durable version.
2. **Revert = a new forward version (append-only).** "Go back to the earlier idea" writes a new
   version whose content equals an old one. History is never mutated or deleted, so
   "reconstruct as-of T" always works — but reverting does not rewrite the past.
3. **Coalesce within a window.** Rapid pre-confirm changes collapse last-write-wins inside a
   debounce window. Only the net state at a checkpoint is recorded.
4. **Materialize lazily.** No draft/trace row per change; recompute from cart versions.

### 4a. Churn as an attack vector (explicit anti-abuse)

Rapid amend/confirm churn is a resource-exhaustion / cost-amplification attack (each cycle can
trigger SKU resolution, routing, draft build, and — post-send — a supplier email). Controls:

- **Rate-limit** amendments per case / per buyer / per window.
- **Reject no-op amendments** (content-identical to current state).
- **Cap post-confirm amendments per case** before requiring human review.
- **Debounce** pre-confirm recompute so a flood of changes yields one recompute.
- These are simultaneously cost controls and security controls — document them as both.

---

## 5. The post-send supersession problem (the hard part)

The cart-confirm boundary keeps *most* churn cheap, but once an RFQ is actually **sent**, the
external world has state: the supplier may already be quoting the old item. After the boundary,
"change my mind" is no longer a redraft — it is a **supersession protocol**:

```
amend-after-send ──► mark prior RFQ SUPERSEDED ──► notify supplier (cancel/replace)
                 ──► re-route + redraft new RFQ ──► GATE 2 (or autonomy)
                 ──► if supplier replies to the superseded RFQ, quarantine/ignore that quote
```

Failure mode to handle explicitly (#6 in the bug catalog): a quote arrives for a superseded
draft. The validator must match an inbound quote to the *current* content-hash and quarantine
quotes for superseded hashes.

---

## 6. Out-of-band supplier contact (the "human supplier called in" case)

A supplier often contacts the merchant outside the system (phone, in-person). That information
must re-enter the bitemporal record and propagate. This is the **write-side** counterpart to the
existing read-only `supplier_inbox_reader`.

Design:
- An operator entry point records an **out-of-band supplier event**: *"Supplier X called —
  lead time slipped to 3 weeks / price changed / out of stock."*
- It **fans out** to every open case + PO + receipt referencing that supplier domain, as a
  durable, append-only note.
- It can **trigger downstream actions**: re-route to an alternate supplier, re-draft, flag the
  PO, notify the buyer.
- Bitemporally, an already-issued PO is **not mutated** — a new fact ("supplier reported delay")
  is appended, so "the PO as-of issue time" is preserved while "the PO as-of now" reflects the
  new reality.

---

## 7. Frontend / UX implications (recommend incremental, not a from-scratch rebuild)

The UX is a **projection of the backend model**, so the model should be settled first. Rebuilding
the wireframe before that is rework. The focused UX changes this model implies:

- **The cart is the commitment surface.** It must clearly distinguish *"draft — nothing ordered
  yet"* from *"confirmed — now sourcing."* Trust depends on the buyer knowing nothing has fired.
- **Show the re-route as a consequence.** When the buyer swaps an item, the panel shows
  *"now sources from <supplier>, lead time N days"* — re-routing becomes visible, not magic.
- **One source of truth.** Eliminate the current split where the chat says one thing and the
  right panel another; both render the same cart/intent state.
- **Live update on change.** The panel updates as the cart changes, reflecting the fluid draft.

Open question for the owner: do we redo the cart component as part of this, or retrofit the
existing one? Recommendation: retrofit first (commitment-state badges + re-route consequences),
evaluate a fuller rebuild only after the model is proven.

---

## 8. Consumer-behavior bug catalog ("will the user think it's dumb?")

The failure modes that make a buyer rage-quit, with current status. These are the acceptance
criteria for the rebuild.

| # | "Feels dumb" failure mode | Status today | Fixed by |
|---|---|---|---|
| 1 | "No, the other one" → still recommends the original (context loss) | ⚠️ Known (NQE context) | Cart intent as source of truth |
| 2 | Changed the cart but RFQ still references the old item | 🔴 Current | Fluid draft projection (§3) |
| 3 | Iterates 5×, admin sees 5 orphaned cases | 🔴 Current | One case per cart, materialized at confirm (§1) |
| 4 | Supplier silently changes — no explanation | 🔴 Current | Visible re-route (§7) |
| 5 | Amends while admin approves old draft → stale approval sent | ⚠️ Partial ("edit voids approval") | Hash-pinned approval + supersession (§5) |
| 6 | Supplier replies to a superseded RFQ | 🔴 Unhandled | Quote-to-current-hash matching (§5) |
| 7 | Double-submit confirm → 2 POs | ⚠️ Needs idempotency | Idempotent confirm (409 replay) |
| 8 | Abandoned cart sits in AWAITING forever | 🔴 No TTL | Cart/case TTL + expiry |
| 9 | "Make it 20" — 20 total or +20? | 🔴 Ambiguous | Explicit quantity semantics + confirm-back |
| 10 | Item swap loses the "$1900 each" budget | ⚠️ Unclear | Budget preserved across amendments |
| 11 | In-stock + needs-sourcing in one cart — does in-stock ship now? | 🔴 Unhandled | Split fulfillment at confirm (§9) |

---

## 9. Partial / split fulfillment at confirm

A confirmed cart may mix in-stock items and items needing third-party sourcing. At confirm:
- In-stock lines → fulfill immediately (existing path).
- Shortfall lines → group by supplier (existing `order_split`) → materialize RFQ case(s).
- The buyer sees a single confirmation that honestly splits *"shipping now"* vs *"sourcing,
  est. N days."*

This composes the existing supplier-split with an availability-split.

---

## 10. Recommended build sequence (phased)

1. **Phase 1 — Fluid intent + lazy draft (backend).** Cart/session holds the fluid intent;
   draft is recomputed as a projection; no durable case until confirm. Debounce + coalesce.
2. **Phase 2 — Cart-confirm = GATE 1.** Confirm materializes the durable bitemporal case(s)
   (supplier-split + availability-split). Idempotent confirm. Abandoned-cart TTL.
3. **Phase 3 — Anti-abuse.** Rate-limit / no-op rejection / amendment caps (§4a).
4. **Phase 4 — Post-send supersession.** Supersede + supplier-notify + quote-to-current-hash
   quarantine (§5).
5. **Phase 5 — Out-of-band supplier write-bus.** Operator records supplier contact → fan-out
   to related cases/POs/receipts (§6).
6. **Phase 6 — UX retrofit.** Commitment-state surface, visible re-route, single source of
   truth (§7).

Each phase is independently shippable and bitemporally traced. Phases 1–2 deliver the core
"redraft until cart-confirm" capability the owner asked for; 3–5 harden it; 6 makes it legible.

---

## 11. What this preserves from the existing platform

- The bitemporal decision trace (everything is already append-only with actor attribution).
- The two-gate safety model (just re-anchored to cart-confirm + send).
- Deterministic supplier routing from the StoreProfile (vertical-blind core).
- The flag-gated autonomous-send path (after-hours hands-off).
- The existing supplier-split (`order_split`) and draft builder (`build_draft`).

Nothing here is a rewrite — it is a re-anchoring of the commitment boundary plus the
hardening the owner identified (revert handling, anti-abuse, out-of-band supplier, split
fulfillment, the consumer-behavior bug catalog).
