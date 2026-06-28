# Alternatives-first, human-qualified bulk procurement (agnostic core)

A bulk buyer request ("30 laptops in 10 days" / "20 chairs" / "15 shirts, size mix") must NOT jump
straight to emailing a supplier. The flow: check the whole fulfilment network for stock → offer the buyer
real alternatives → have a human confirm the buyer is serious → only then engage the right supplier(s).
Every step is bitemporally traced. All vertical vocabulary lives in the StoreProfile; core does only
quantity / location / attribute math (same logic for laptops, chairs, or shirts-by-size).

## Target flow
```
bulk request (qty ≥ threshold)
  → open procurement case (REAL top SKU, not a placeholder)
  → assess availability ACROSS locations (preferred store, other stores, warehouses)
  → if shortfall: GENERATE alternatives → surface on the 5173 right panel → buyer picks
        trace: stock_insufficiency_found, alternatives_presented
  → HUMAN admin qualifies the buyer (escalation room): serious? confirm scope/qty/deadline
        trace: buyer_qualified  (human-verified; gate before any supplier contact)
  → record the chosen alternative
        trace: alternative_selected
  → draft RFQ to the right supplier(s) — multi-supplier per SKU when needed (WS-B)
  → human GATE 2 approves + sends (WS-C/D); autonomous send only if flag + guards (WS-C)
```

## Alternatives taxonomy (agnostic — attributes come from the profile)
1. Substitute SKU / variant — nearest catalog item by profile attributes (brand/spec; size/colour; model)
2. Partial now + backorder the remainder (split delivery)
3. Inter-store / warehouse transfer — consolidate stock from other `location_id`s to the buyer's preferred location
4. Reduce quantity to what's on hand
5. Reorder shortfall from supplier(s) — single or split across multiple suppliers (speed / price / risk)
6. Volume price-break — higher qty unlocks a tier (asked in the RFQ)
7. Lead-time vs price tradeoff — faster-pricier vs slower-cheaper supplier
8. Staggered / scheduled delivery — e.g. 10 now, 20 next month
9. Spec / budget renegotiation — in-budget lower spec, or the budget the spec actually needs
10. Hold / reserve available stock during qualification (no stockout mid-conversation)
11. Fleet add-ons — warranties / accessories / setup as a bundle (complementary SKUs)
12. Mixed-variant fill — size/colour mix sourced across locations/suppliers

## What exists vs. what's new
- EXISTS: `inventory_level(sku, location_id, on_hand, reserved)` (multi-location data); `options.py`
  shapes (substitute/split/reduce — accepts a substitute, doesn't generate); RFQ fan-out + compare-quotes
  (multi-supplier); fulfilment state machine + draft + bitemporal trace; escalation room (buyer↔staff).
- NEW: multi-location availability (use `location_id`, propose transfers); an agnostic **alternatives
  generator** (substitute candidates by profile attributes; transfer; split; reduce; multi-supplier);
  the **5173 right-panel bulk view**; the **buyer-qualification bridge** (escalation room ↔ case);
  new trace events/states (`stock_insufficiency_found`, `alternatives_presented/selected`,
  `buyer_qualified`).

## Phases (each: edit → compile → tests → ratchets → commit)
- **P1 — Bulk spine + P0 fixes.** Cases open on a real bulk query with the real top SKU; multi-location
  availability; budget-leak fix (cap the narration band at the buyer's ceiling + tag over-budget
  lane items). Resolves "no pending supplier email" + the $5,999 trust regression.
- **P2 — Alternatives engine + 5173 right-panel bulk view.** Generate the taxonomy above; buyer selects;
  bitemporal `alternatives_presented/selected`. Agnostic-core (profile attributes drive substitution).
- **P3 — Buyer-qualification bridge.** Wire the escalation room to the case; `buyer_qualified` event is
  the human gate BEFORE supplier contact.
- **P4 — Supplier engagement per chosen alternative.** Multi-supplier auto-draft → human GATE 2 (WS-B/C/D).
- **Parallel — P1 UI cleanup.** Off-domain image grouping suppressed; security warning as its own block;
  NQE question de-dupe; Top-Reco missing Add button + narration bleed.

## Agnostic-core guardrails
The alternatives engine, multi-location availability, and qualification gate all graduate into
`_CORE_MODULES`. No product vocabulary in core: substitution ranks by the profile's
`narration_spec_dimensions` / attribute slots; "store/warehouse" are opaque `location_id`s; the
buyer-facing strings come from the profile. Ratchets (no-flavour / no-silent-except / no-untimed-http)
stay green.
