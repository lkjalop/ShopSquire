# Consolidation checkpoint and remaining release blockers

Date: 2026-09-07. This is an implementation/verification receipt, not production certification.
Earlier assessment documents are preserved as historical observations, not instructions or current pass certificates.

## Recovery and source checkpoints

- Original baseline: `be3382b9`.
- Complete pre-change backup: `C:/AI/ShopSquire-checkpoints/pre-p0-20260907-111701`.
  Includes the HEAD archive, all 72 modified/untracked files and SHA-256 manifest.
- `1206a1ca`: dependency-complete baseline, including previously untracked imported modules.
  These changes share imports across model, catalog, evidence and frontend paths; splitting
  them arbitrarily would create broken intermediate checkouts.
- `08d68634`: public readiness contract allowlist, with a secret-canary regression.
- `1d8ba3ab`: predicate IDs, requirement review labels/values, source-applicability guard,
  and authority-based terminal catalog gating, with service and live-browser regressions.
- No reset, clean, deletion, source approval, supplier sending or remote push performed.
- Logs, databases, screenshots and browser traces remain outside source commits.
- The remaining `config/feature_flags.json` status entry has no substantive Git diff and
  has deliberately not been reset or rewritten.

## Repairs verified

1. Structured claims now have deterministic per-predicate IDs, not one Steam app ID reused
   for RAM and VRAM. Changes in value, tier, condition or source revision change the ID;
   ordering does not. Original provider claim IDs remain separate provenance.
2. Official verified values are displayed read-only with their actual authority. Buyer
   acceptance does not re-approve them. This fixes the observed RAM 8 displaying as 2.
3. Proposal-grade scope aliases such as CAD cannot select another application's canonical
   source. FreeCAD no longer inherits AutoCAD requirements through this planner branch.
   This is not a complete proof of every open-world source-applicability path.
4. Blocked authority clears terminal catalog projections; candidates with unknown or
   provisional authority are not labeled qualified. This still relies on upstream fit
   authority being correct: shelf presence is no longer sufficient to declare qualification.
5. Public readiness exposes an allowlist rather than the private runtime contract. Live
   `/readyz` no longer includes API keys or database/Redis connection strings in `config.contract`.

## Verification performed

Clean worktree: `C:/AI/ShopSquire-checkpoints/verify-baseline-20260907`.
Python and node dependency installations were reused. This is clean-source verification,
not a clean-machine dependency installation or hosted certificate.

| Gate | Result |
| --- | --- |
| Baseline clean-checkout focused backend suite | 47 passed |
| Readiness commit clean-checkout suite | 5 passed |
| Evidence commit clean-checkout consolidated suite | 60 passed |
| Recommendation-core and bulk/shortfall service suite | 249 passed |
| Clean-checkout frontend unit suite | 354 passed, 78 files |
| Clean-checkout frontend build | Passed |
| Two new live Playwright evidence-delivery regressions | 2 passed, one worker, zero retries |
| Architectural guard suite | 3 failed, 2 passed; ceilings unchanged |

Red runs reproduced claim collision, authority-label, public-secret and source-applicability
failures before fixes. Four authority-gate assertions also failed before the gate change.
Some tests overlap between suites; these counts must not be added as unique coverage.

The real-browser diagnostic battery also exercised shapez 2, FreeCAD, a chair, a refrigerator,
an unrelated moon question and 25 gaming laptops. No response interception or mock model
was used. All 15 Decision Trace leaves loaded on the game journey without HTTP errors.
The diagnostic's broad `404` text scan falsely flagged a UUID in the Raw tab; it was not
a failed trace request. Loading a tab is not proof its contents are correct.

Artifacts: `C:/Users/leoma/AppData/Local/Temp/shopsquire-assessment-20260907/`;
clean-checkout logs: `C:/AI/ShopSquire-checkpoints/`.

## Still wrong in the live browser

- **Catalog scope:** usually null; bulk scope can be present with null case/revision.
  Normal core products and governed configuration candidates still need one scope boundary.
- **Semantic routing:** a chair receives a generic clarification; an unrelated factual
  question still enters publisher discovery. Buying laptops for a training lab can invent
  a workload research obligation. Do not fix this with application-name exceptions.
- **Trace projection:** summary says Not executed while research reports completed and
  accepted claims. Completeness can say complete despite partial requirement compilation.
- **Bulk feasibility:** quantity and per-unit budget are retained correctly. The 25-laptop
  journey computes zero budget shortfall but leaves stock/transfer/supplier shortfall null,
  and took about 63 seconds in this run. This is not a verified fulfillment result.
- **Narration:** FreeCAD's later run blamed interpreter unavailability; other research
  outcomes and causal failure labels still require reconciliation before narration.
- **Scope and authority:** the qualification gate fix does not certify CPU/GPU compatibility,
  configuration applicability, or a complete fit ledger merely because RAM/VRAM were compiled.
- **Architecture:** blocking DB work in an async case route, broad-exception ratchet debt
  and source-file size ceilings still fail. None were relaxed.

## Next implementation order

1. Characterize semantic purchase-object/workload/unrelated exits with the existing typed
   contract. Use its validated purchase object for server scope, not every noun in the turn.
2. Build and apply CatalogScope once before retrieval, preserving it through all terminal
   exits and binding it to the committed case revision. Reconcile the legacy product and
   configuration catalogs before imposing an ID filter that could erase valid stock.
3. Commit fit/authority/requirements completeness once, then derive narration, questions,
   all trace summaries and shelves from that result. Assert exact rendered values and IDs.
4. Wire separate budget and stock shortfall facts into draft-only sourcing. Browser-test
   explicit acceptance and separately assert no supplier send. Unknown stock must stay unknown.
5. Add failure injection, stale confirmations and multi-turn cases to a seed-recorded
   rotating live set. Keep the exact reproduced failures as permanent regressions.
6. Only then extract orchestration into existing owned boundaries, remove synchronous DB
   work/broad catches, and rerun full service/integration/architecture suites without ratchet increases.
7. Complete independent source reviews, clean PostgreSQL and hosted clean-machine gates.

The platform is a recoverable, partially verified demo, not yet a release-certified shopping assistant.
