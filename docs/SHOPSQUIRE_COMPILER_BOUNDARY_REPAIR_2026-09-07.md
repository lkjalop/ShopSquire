# Compiler boundary repair — first implementation checkpoint

7 September 2026. Partial implementation receipt; not a release certificate.

## Implemented

- Structured source units are validated and converted together with numeric values. A numeric RAM claim with unit `mg` is rejected rather than relabelled GB.
- Operators are checked against attribute kinds. Numeric `contains` is rejected.
- Non-finite values and confidence are rejected.
- Predicate IDs hash source identity and predicate contents; a provider record is no longer the predicate ID.
- Rejection receipts retain the attribute, source record, claim origin and bounded source excerpt.
- Approved tenant documents are no longer automatically marked publisher-verified by the compiler.
- Frontend claim projection requires explicit verification; missing/unverified status is not promoted to `verified_official`.
- Connector-local compiler rejections contribute to terminal rejected-claim counts, deduplicated across repeated receipt projections.
- The GPU comparison-table threshold is explicitly tagged derived and rejected for authoritative compilation (`derived_claim_requires_policy`). The publisher GPU excerpt remains in the rejection receipt and original provider evidence. No replacement literal GPU parser was invented.

## TDD evidence

Seven compiler boundary tests failed before the first repair. Projection/rejection-count tests and the GPU provenance test also failed before their respective changes.

Final verification:

- 81 focused compiler, registry, outcome, structured-claim, workload, terminal and sourcing-projection tests passed.
- 240 recommendation-core envelope, brain, gates, ranking, stages and evidence-stage tests passed.
- Combined rerun: 321 tests passed, native pytest exit 0 (`compiler-final-suite.log`). The final command explicitly propagated the native exit code to avoid PowerShell stderr-warning redirection being mistaken for test failure.
- `git diff --check` passed; Git reports existing LF/CRLF conversion warnings.

Logs are outside source control in `C:/AI/ShopSquire-checkpoints/test-isolation-20260907/`:

- `compiler-boundary-red.log`
- `projection-boundary-red.log`
- `gpu-provenance-red.log`
- `compiler-provenance-suite.log`
- `compiler-core-suite.log`

No browser or live-server restart was performed for this implementation checkpoint. The prior assessment's browser results describe the pre-change process, not these patches. No full service/integration suite, clean checkout, PostgreSQL or hosted certificate is claimed.

## Still required

1. Explicit tenant/product/relationship/manifest-revision scope through both compiler callers. The compiler still uses the global registry union; cross-category authorization is NOT fixed in this checkpoint.
2. Separate allowed uses from attribute role, including scoped storage-fit permission. Storage remains rejected until that contract is implemented.
3. Full observed/derived/accepted ledger with versioned derivation rules and approval provenance. Rejecting ungoverned derivations is containment, not the finished derivation capability.
4. Category-specific completeness. Parsed minimum/recommended sections must not substitute for fulfilled compatibility obligations.
5. Terminal-derived Summary/Why/Evidence and other trace projections. Correcting one rejection count is not full trace reconciliation.
6. Literal GPU/CPU/OS compatibility evidence and the positive product-delivery browser gate. PRAGMATA qualification is not declared fixed.
7. Separate live budget/stock-shortfall and explicit sourcing acceptance tests. Existing focused sourcing tests passed, but this is not a live dispatch-absence certificate.
8. Reviewed cross-category manifests and packaging; independent human reviews remain outstanding. No sources were approved.
9. Cohesive extraction with unchanged architecture ceilings and deployment certification.

The live server has not been reloaded onto this checkpoint. Changes remain uncommitted. Existing dirty files and assessment documents were preserved; no reset, deletion or push occurred.
