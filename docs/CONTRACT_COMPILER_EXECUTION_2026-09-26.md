# Contract/compiler execution — 26 September 2026

Implemented the next boundary from the two roadmap reports: explicitly selected requirement contracts can now gate the existing authoritative compiler and typed semantic evidence stage. This is compiler/stage support, not completed buyer-case activation or a qualified Blender journey.

## Changes

- `compile_authoritative_requirements` accepts a typed contract and selected context as separate caller arguments. Provider fields cannot supply that selection. Existing callers retain their existing scope/registry behavior.
- `contract_compilation_gate.py` checks the selected contract against accepted evidence, source enrollment for each obligation, explicit applicability, application identity/version, provenance, observation time, expiry, revocation, conflicts and derivation status. It contains no application-name or manufacturer logic.
- Per-input indices bind eligibility to the exact row, so duplicate provider claim IDs cannot smuggle an unrelated predicate through the contract gate.
- Contract coverage and successful compilation are separate receipts: `coverage_complete` versus `compiled_complete`. An unsupported registry attribute can have source coverage without becoming executable.
- Compilation is atomic for a selected contract. If any required obligation fails compilation, the successfully compiled subset is quarantined too. Raw evidence remains available; no partial predicate set is returned as executable requirements.
- `resolve_semantic_evidence_stage` accepts the explicit selection, preserves the coverage result in its concept data and removes provider catalog-qualification candidates when the contract fails compilation. Search consent and the existing attribute/scope checks remain in force.

## Evidence

[53 targeted checks passed](../.artifacts/contract-compiler-2026-09-26/final-tests.xml), covering existing compiler and provider behavior, generic contracts, stage coordination, duplicate IDs, absent context/scope, mismatched versions, stale/revoked evidence, unsupported attributes and partial-compilation quarantine. The stage test also proves provider qualification candidates cannot survive a failed selected contract.

The [recorded Blender compilation](../.artifacts/contract-compiler-2026-09-26/blender-compilation.json) sends the 19 previously fetched source claims through this actual compiler with the bounded contract. Result: zero executable requirements, incomplete coverage and incomplete compilation. The missing applicability/compatibility evidence has not been replaced with assumptions.

Function-size, undefined-name and repository diff checks passed. No real messages or financial effects were sent. No source authority, observation timestamp, product qualification or model benchmark conclusion was upgraded.

## Remaining delivery boundary

The current top-level buyer flow does not yet select a contract automatically. The newly added arguments must come from a persisted, tenant/case/revision-bound selection, not from model output or inferred software keywords. Before activating this for buyers:

1. Persist selection and immutable contract revision with explicit application/platform/workload context, and invalidate it when the case changes.
2. Preserve that binding in compiled receipts and recheck it at consumption. A later contract edit, revocation or scope change must invalidate prior qualification.
3. Enroll version-specific official evidence and obtain an acceptable manufacturer capture/document. Existing MSI observations remain held.
4. Define reviewed typed compatibility predicates and application obligations independently of the generic electronics manifest. Do not remove its existing requirements merely to obtain a passing showcase.
5. Verify API/UI/trace agreement through a complete qualified journey and the failure cases.

Distinct-person approval, effect recovery, sustained reliability, real tenant market data and representative benchmarks remain open. This batch does not certify those gates.
