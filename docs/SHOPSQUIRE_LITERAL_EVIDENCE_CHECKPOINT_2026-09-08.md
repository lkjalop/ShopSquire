# Literal evidence delivery checkpoint

8 September 2026. Partial implementation; not a release certificate.

## Fixed

- Steam parsing/bounding now retains literal CPU requirements instead of dropping them.
- Live minimum and recommended sections retain bounded CPU/GPU/OS source-line receipts. Offsets refer explicitly to normalized publisher lines, not original HTML bytes.
- Bounding validates that the cited substring exactly equals the retained value. Forged, invalid or normalization-mismatched spans are dropped rather than manufactured.
- The structured provider projects immutable observations tied to canonical title, provider record, source URL, observation time and requirement section.
- Observations remain `observed`, with `fit_authority: none`. GPU alternatives are not converted into an invented scalar or exact-string compatibility predicate.
- Both resolved and incomplete workload evidence preserve those observations. The research outcome deduplicates them without counting them as accepted predicates.
- The shared summary displays literal observations under an explicit “not compatibility verification” disclosure.

## Tests

New parser, forged-span, provider-identity, outcome and UI assertions failed before their respective repairs.

- Combined backend suite: **364 passed**, native exit 0.
- Shared-summary frontend tests: **2 passed**.
- Frontend production build: passed.
- Diff whitespace check: passed; existing line-ending warnings remain.

Evidence is outside the repository under `C:/AI/ShopSquire-checkpoints/test-isolation-20260907/`: `literal-evidence-red.log`, `literal-projection-red.log`, `literal-outcome-red.log`, `literal-ui-red.log`, `literal-final.log`, `literal-ui-green.log`, `literal-build.log`.

The combined verification tool return was delayed approximately twenty minutes, but pytest completed and returned exit 0. Its cause was not established; this is not evidence of an OOM diagnosis.

## Not yet done

1. Typed CPU/GPU alternative parsing and compatibility evaluation against catalog evidence, with exact workload identity applicability. Preserved literal observations are not compiled fit proofs.
2. Full source-span capability for other provider/document formats and numeric RAM/storage transformations.
3. Reconciliation of all legacy trace panels with terminal truth.
4. Positive product-delivery browser gate, separate budget/stock shortages and draft-only sourcing acceptance.
5. Cross-category fixtures/packaging, durable manifest publication and extraction.
6. Clean-checkout/PostgreSQL/hosted certification and independent source reviews.

No live API restart or browser certificate was performed in this checkpoint. Changes remain uncommitted; existing work was preserved. No sources were approved, no supplier was contacted, and nothing was pushed or deleted.
