# Test isolation and bounded semantic repair — 2026-09-07

Status: local TDD checkpoint, not a release or live-browser certificate.

## Preserved configuration

Before changing configuration, copied the dirty file to:
`C:/AI/ShopSquire-checkpoints/test-isolation-20260907/feature_flags.before.json`.
SHA256: `5F4570CA0A91C7C172EAC509DAAA86B8E3FCCF206D3E8546168229C439CE419A`.

Restored the tracked configuration's committed content after preserving the test
pollution. Git may still mark the file modified due to line endings; it has no
textual diff. No source review, runtime authority, or external-search profile was
changed to make tests pass.

## Changes

- Pytest collection uses a disposable flags file, not the repository configuration.
- Existing per-test snapshot/restore resets settings and feature-flag caches.
- The shared test writer follows FEATURE_FLAGS_PATH and refuses the tracked file.
- Five affected test modules snapshot/restore the same disposable path they write.
- Chat's query-budget projection delegates exclusively to the canonical grammar;
  a declined parse remains declined rather than invoking legacy regexes.
- The taxonomy fallback preserves a compound category's trailing head before
  applying storefront preference. This repairs the reproduced computer-chair
  case without a chair/application-name exception. It is NOT a complete typed
  purchase-object/negation/mixed-intent implementation.

## TDD and verification

- Red: two flag-writer regressions and employee-range budget parity failed.
- Red: both computer-chair/storefront regressions failed.
- Expanded local run: 46 tests passed; exit 0; config hash unchanged.
- Reversed affected order plus additional cache/catalog tests: 57 tests passed;
  exit 0; entire tracked Git diff unchanged by that run.
- Recommendation core stages, ranking, gates, envelope, brain, subject-role and
  clarification suites: 273 tests passed; exit 0.
- `git diff --check` passed.

Counts overlap across runs and must not be summed into a full-suite certificate.
Logs are outside the repository under the checkpoint directory above:
`expanded.log`, `final-reverse.log`, `core.log` (earlier red/order logs also retained).

## Still required, in order

1. Complete typed purchase/workload routing for negation, mixed requests and
   subject switches; characterize form-factor shortcut behavior too.
2. Seal a real browser delivery gate: complete accepted evidence and matching
   permitted inventory must produce a qualified shelf. Independently exercise
   held/partial evidence, budget versus stock shortfall, draft-only sourcing,
   stale revisions and all Decision Trace tabs.
3. Extract terminal projection, then research orchestration, into owned typed
   boundaries. No source-size ceilings were changed in this checkpoint.
4. Finish stable concept IDs and typed identity/modifier propagation.
5. Live failure injection, clean PostgreSQL and hosted certification, independent
   source reviews, and consumer audit before retiring legacy APIs.

No live model/browser run, server restart, remote push or legacy archival was
performed for this checkpoint. All changes remain uncommitted.
