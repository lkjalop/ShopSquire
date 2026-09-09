# Compiler-to-fit wiring repair — 2026-09-09

## Implemented

- Registry evaluation accepts compiler equality (`=`), retaining legacy `==`.
- The existing constraint normalizer accepts the same equality syntax.
- Compiler no longer authorizes substring text claims as hard fit predicates. CPU/GPU compatibility requires typed identity/capability evaluation, not substring overlap.
- Structured-provider projection preserves typed values and all distinct predicates in a list. It no longer casts OS/model values to float or uses a numeric maximum to collapse upper and lower bounds.

## TDD evidence

New equality and substring-authority tests both failed before repair. The provider projection regression then reproduced `ValueError: could not convert string to float: 'Windows 11'`. Its downstream normalization assertion exposed the second equality mismatch. Existing single-predicate connector assertion was updated to the list-shaped contract; no authority or product-delivery assertion was weakened.

Final test receipt: `C:/AI/ShopSquire-checkpoints/pilot-review-20260909/compiler-fit-verified.xml`. Includes compiler, scope, provider grounding, outcome, evidence stage, attribute registry, constraints and recommendation-core stages. Earlier red receipts remain alongside it.

## Not certified by this repair

No live server restart/browser certification, source approval, supplier dispatch, manifest database publication or checkpoint commit was performed. Existing dirty changes were preserved. Full typed CPU/GPU/OS compatibility, exact resolved product scope propagation, identity-bound completeness, terminal trace reconciliation, positive delivery and shortage browser gates remain required. The patch does not make partial evidence complete or permit previously held derivations.
