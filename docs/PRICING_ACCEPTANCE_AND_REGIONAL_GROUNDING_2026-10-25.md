# Pricing acceptance and regional grounding

Reviewed during the 24–25 October 2026 implementation session. This records the deliberate acceptance decision requested by the user, its alternatives, and the remaining limits. It is not a claim that ShopSquire can transact globally or calculate every jurisdiction's taxes.

## Decision

Use a grounded, read-only comparison for the MVP. Distinguish an observed price, a merchandise comparison, a complete reviewed quote, approval, and an actual effect receipt. A GET suggestion, a passing policy check, an inserted audit row or an approval does not prove that a price or cart changed. GET is a safe method under [HTTP semantics, RFC 9110 §9.2.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.1); incidental logging does not make it a purchase operation.

| Alternative | Benefit | Reason for the decision |
|---|---|---|
| Relax the verifier to preserve the old executed/pending assertion | Small test change; apparent green | Rejected: the recorder has no price/cart executor. This would certify a fictional action. |
| Require review for every displayed number and suppress all candidates | Conservative | Insufficient product usefulness: a current, attributed same-currency merchandise comparison is still useful without purchase authority. |
| Separate evidence, comparison, complete quote and effect | Useful comparison with explicit authority | Chosen: retain source/currency/quantity basis, hold missing costs and conversions, and reserve executed for an actual verified effect. |

The existing generic decision verifier remains enabled. Its checks are limited shape/policy checks; they do not authenticate a cart or establish the truth of a supplier quote. The fixture's `v-test-1` policy is not registered to make the legacy test pass.

## Deliberate contract migration

`GET /api/v1/pricing/suggest` now returns `pricing-preview-v2`, the requested supported currency, `price_basis=unverified_cart_amount`, `executed=false`, `execution_status=review_required` and `action_authority=none`. Existing proposal/firewall fields remain. The historical AUD rules are illustrative; USD/EUR requests receive no invented regional discount. Other currencies require an implemented, tested contract rather than defaulting to AUD. Operator authentication, the autonomy kill switch and the pricing-capability gate remain required.

`Orchestrator.execute_or_escalate` retains its historical callable name but records a pricing proposal. It no longer returns true for an action it did not perform, including when logs are disabled, simulation is requested or audit persistence fails. A preview does not consume a commercial idempotency key. Proposal persistence records planned/pending, with the strict verifier still able to require review.

The last assertion in `test_decision_logs_fields.py` was intentionally migrated from executed/pending to review_required and strengthened with preview-authority and failed-policy-verifier checks. This is an acceptance change, **not** an unchanged-expectation bug repair. Preserve the earlier red full-suite evidence when reporting the delta. Separate new tests reproduced false execution and then retained their expectations through the repair.

## Real observations used as fixed test inputs

Captured from the manufacturer's public pages on 24 October 2026 at approximately 13:02 UTC. Values can change. Raw-page hashes and observation times are in [the fixture](../tests/fixtures/regional_price_observations_2026-10-24.json). These are product-family/pack observations; exact cross-region SKU equivalence, current stock and tenant quote approval were not certified.

| Store | Single pack | Four pack | Source |
|---|---:|---:|---|
| Australia | AUD 49.00 | AUD 165.00 | [Apple Australia](https://www.apple.com/au/shop/buy-airtag/airtag/1-pack) |
| United States | USD 29.00 | USD 99.00 | [Apple US](https://www.apple.com/shop/buy-airtag/airtag/1-pack) |
| Germany | EUR 35.00 | EUR 119.00 | [Apple Germany](https://www.apple.com/de/shop/buy-airtag/airtag/1er-pack) |

The regional reducer tests use the single-pack values as fixed merchandise amounts on explicitly fictional case/SKU records. They exercise the actual case commercial projection, not a live Apple checkout or an asserted stock feed. Four-pack observations are retained to make the unit/pack gap visible; the current test pack is not a certification of arbitrary unit-of-measure normalization.

For example, 40 single packs and ten four-packs have different prices and sellable pack identities. A 25-item shortage would require seven indivisible four-packs, yielding 28 items; the three excess items need explicit handling. Do not divide a pack price and silently authorize a fractional pack or change a 25-item enquiry to 25 packs.

## Why the regions need different evidence

Australian consumer displays generally include taxes and unavoidable/preselected fees. The ACCC separately permits business-only displays to exclude GST. ShopSquire must record buyer context and price basis instead of assuming every supplier quote includes GST. The current ACCC page also records changed card-surcharge rules from 1 October 2026; an old generic payment-fee assumption should not become current Australian policy. [ACCC price displays](https://www.accc.gov.au/business/pricing/price-displays).

Apple US explains that its sales/use tax follows the shipping or pickup address, with checkout estimates and a final invoice amount. A US country code or USD price is insufficient to calculate that tax. The FTC's specific fee rule covers live-event tickets and short-term lodging; it is not a universal retail tax/display rule. [Apple US tax information](https://www.apple.com/shop/help/payments), [FTC fee-rule scope](https://www.ftc.gov/business-guidance/resources/rule-unfair-or-deceptive-fees-frequently-asked-questions).

EU consumer guidance requires clear complete price information, including taxes/delivery and disclosure of extras that cannot yet be calculated. Germany is the concrete example here; EUR alone does not identify the applicable country or buyer tax treatment. Discount/personalisation disclosures need their own policy review before that feature ships. [Your Europe pricing guidance](https://europa.eu/youreurope/citizens/consumers/unfair-treatment/unfair-pricing/index_en.htm).

The ECB's 23 October reference was EUR 1 = USD 1.1193 / AUD 1.5939. The ECB labels these informational and discourages transaction use. That observation is not an approved tenant conversion, a checkout rate or a promise about bank fees. A reviewed conversion must retain pair, direction, rate, timestamp/expiry, rounding and policy approval. [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).

## Implemented comparison safeguards

- The case commercial reducer requires known, matching budget and price currencies before declaring budget fit. Missing/mismatched currency stays unknown and unverified; no live FX is inferred.
- Conflicting supplier quote prices/currencies cannot collapse into the minimum price for the entire order. Sufficient stock can establish quantity coverage independently of price completeness.
- Product shelves retain foreign-price candidates for explicit budget review, outside within/stretch claims. Raw nominal amounts do not rank mixed-currency ties or create a cheaper-alternative claim.
- Existing high-value advisory thresholds remain AUD-denominated; another currency needs a reviewed tenant policy.
- These are merchandise comparisons. Freight, duties, destination tax, minimum order, payment terms and quote expiry still need explicit evidence before a landed total is complete.

## Required next controls

1. Bind each reviewed quote to tenant, case/revision, exact configuration/pack, quantity, destination, validity window and immutable version.
2. Sum priced allocations: local stock, each supplier lot, minimum order and pack rounding. Do not assign one lot's unit price to all stock or use a minimum across conflicting quotes.
3. Distinguish tax-inclusive, tax-exclusive, exempt and unknown; prove a known zero separately from a missing field. Do the same for freight and duties.
4. Carry complete price basis and remaining unknowns into the buyer preview and reviewed supplier draft; disclose the buyer's budget only when selected.
5. Run AU consumer/B2B, US destination changes and multiple EU-country cases through browser amendments/reload, including approved FX and rejected stale/reversed/unapproved conversion controls.
6. Only an explicit effect endpoint may consume an exact, current approval. Verify the resulting mutation/provider receipt, retry semantics and reconciliation before setting executed.

Code/test entry points: [commercial reducer](../src/app/services/commercial_decision_reducer.py), [case projection](../src/app/services/shopping_case_commercial_projection.py), [product shelves](../src/app/services/recommendation_core/product_shelves.py), [preview API](../src/app/routers/pricing.py), [regional controls](../tests/services/test_regional_price_grounding.py), [preview controls](../tests/api/test_pricing_preview_contract.py), [recording controls](../tests/services/test_pricing_preview_authority.py).

## Verification scope

On the independently assembled committed baseline plus this pricing cohort, 112 selected tests passed with zero failures, errors or skips, including existing recommendation parity, canonical-cart, rollout, quality-verifier, metrics and chaos controls. Changed-file Ruff passed. Earlier controls retained their behavioural expectations: regional case money reproduced 20 failures; regional shelves reproduced six; the proposal recorder reproduced three false-execution failures; the initial preview API controls reproduced six failures. This targeted result is separate from the explicitly migrated legacy assertion and is not full-release green. Raw local run receipts and captured pages are retained under `.artifacts/implementation-2026-10-24`; they include private fixture data and are not publication artifacts.
