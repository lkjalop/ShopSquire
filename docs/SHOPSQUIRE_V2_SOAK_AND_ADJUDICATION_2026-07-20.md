# ShopSquire V2 Soak and Adjudication - 2026-07-20

## Sealed evidence

| Evaluation | Result | Artifact |
|---|---:|---|
| 20 journeys x 10 context turns | safety 100%; continuity 100%; routing 77%; p95 6.24s | `tmp/synthetic_soak/context_20x10_20260720_final.json` |
| 14 journeys x 15 lifecycle turns | safety 100%; continuity 100%; routing 58.1%; p95 6.06s | `tmp/synthetic_soak/lifecycle_14x15_20260720_final.json` |
| Sealed facade replay | fallback 0%; constraints 100%; P@10 84.4%; NDCG@10 86.6%; p95 8.078s | `tmp/quality/shadow_replay_20260720.json` |
| Hippograph off vs shadow-on | NDCG 0.4737 vs 0.4737; delta 0 | `tests/characterization/hippograph_ndcg_ab.py` |

Synthetic relevance remains explicitly unmeasured. The eight draft slates still require an
independent human review before their quality scores can authorize promotion.

## Routing calibration

The lifecycle failures are not continuity or semantic-safety failures. They are concentrated in
mixed procurement turns: supplier-channel and no-send questions commonly resolve to
`POLICY_QUESTION`, while quote/amendment commands sometimes resolve to `SEARCH`. Before changing
the model prompt, split the expected behavior into `PROCUREMENT_ADVICE`, informational policy and
consequential procurement commands at the evaluation layer; execution continues to use the one
existing `PROCUREMENT` lane and mature fulfillment workflow.

## V1/V2 adjudication

### Confirmed V2 regressions

1. `filter_followup:1`: the explicit `16GB RAM` floor was weakened to the KB's 8GB default when
   the model omitted the explicit value. Fixed by `b679560`: keyed quantity evidence is now
   recovered from the data-driven attribute registry and cannot be weakened by model output.
2. `compare_two_models:0`: `COMPARE` returns a generic gaming slate rather than binding the named
   Dell and Lenovo products. This remains open and must block COMPARE canary promotion.
3. Currency authority: the catalog contains AUD and USD prices while `TurnEnvelope` has no buyer
   or store currency. Numeric budget filtering therefore compares unlike currencies. This remains
   open and must block budget-sensitive canary promotion for mixed-currency tenants.

### V1 behavior to mark known-wrong

- `accessory_bag:0`: V1 returned no products; V2 returns two active, taxonomy-grounded laptop bags.
- `compare_two_models:0` V1 escalation flag: an ordinary product comparison was marked escalated.
  V2 correctly does not create a security/escalation event. This does not excuse the V2 named-item
  binding regression above.

### Accepted V2 contract changes

- `off_domain:0`: both versions show no products; V2 uses an explicit no-results contract rather
  than a clarification-only legacy shape.
- `offcatalog_paraphrase:0`: both refuse safely with no products. V2 records a taxonomy handle
  rather than the legacy hard-coded class name. The selected node is semantically imprecise and
  remains a router-quality diagnostic, but it is not a sellability or authorization failure.
- `explain_followup:1`: V2 uses `caution` rather than legacy `auto` autonomy for recommendation
  explanation. The more restrictive V2 gate is accepted.
- `cart_swap_via_suggest:0`: cart mutation is delegated and not canary-eligible. V2's no-product
  response is acceptable only while the backend cart lane remains the authoritative handler; it
  is an archive dependency, not parity work.

### Diagnostic, not a promotion gate

The remaining MAJOR rows (`brand_negation`, budget cases, search cases, persona/workload cases and
the first filter/explain turns) are dominated by product-set breadth and legacy response-shape
differences. V2 showed only active, authorized, in-budget and capability-satisfying products in the
sealed run. Keep these differences visible, but adjudicate relevance through the sealed human
labels rather than forcing V1 SKU identity.

## Promotion decision

Do not start real canaries yet. Required gates are:

1. human-seal the eight relevance slates;
2. define and enforce a tenant/store budget currency, with conversion evidence or same-currency
   exclusion;
3. bind named products in `COMPARE` and rerun that case;
4. obtain three sealed replay passes with p95 at or below 8 seconds (the current run missed by
   78ms);
5. improve or explicitly accept procurement routing calibration by turn subtype;
6. finish the live IMAGE battery and migrated deployment/browser proof.
