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

## Subsequent execution — checkpoint and live gate

The statement above records the earlier run. The repairs are now committed as
`b85d16bd`; `5c41f513` additionally preserves a model-proposed host/workload
relationship when both device and execution relation are literal buyer facts,
and makes the feedback fixture's model response explicit. `b1c7f073` adds safe
failure diagnostics. Nothing was pushed.

Two new purchase-verb/host-workload tests failed before the role correction.
The local subject-role plus feedback test run then passed 21 tests.

Clean detached checkout verification is NOT green: the feedback projection
integration test still fails without the demo worktree environment, even after
an explicit primary core mode and valid router fixture. The dependency remains
unresolved; do not call this clean-machine or PostgreSQL certification.

Restarted the demo stack and prewarmed qwen3:14b. Browser certification used
one worker, GPU-disabled Chromium and zero retries:

- Unrelated question: passed.
- Bulk stock accounting: passed.
- Computer chair: failed; terminal message is now truthfully router-output-invalid.
  The independent scope fix does not eliminate this model-result failure.
- PRAGMATA positive delivery: failed; identity/research worked and two claims
  were accepted, but narration omitted the title and coverage remained partial.
  This is not a qualified-product success.

Browser traces/screenshots and logs are in the external checkpoint directory:
`browser-results`, `delivery-results`, `browser.log`, `delivery.log`, and
`clean-final.log`. Full tab-content, supplier-send absence, mixed/negated roles,
and complete-evidence positive delivery are not sealed by this run.

Large extraction and legacy retirement remain deferred until those gates pass.
