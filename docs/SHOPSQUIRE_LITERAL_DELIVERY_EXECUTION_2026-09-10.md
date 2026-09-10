# Literal delivery execution — partial verification

## Implemented

- Structured claim projection preserves cited excerpts, spans, document revision and manifest scope; snapshots do not alias provider data.
- Connector compilation retains exact, cited CPU/GPU/OS/storage-type predicates and canonical title. No performance equivalence is inferred.
- Electronics manifest no longer translates generic SSD into SATA SSD.
- Authorized live Steam lookup no longer silently returns curated fixtures. Offline lookup remains fixture-backed; live failure is explicit.

## Executed evidence

- Missing literal compilation and fixture-shadowing regressions failed before their fixes.
- 48 focused connector/compiler/projection/delivery tests passed (`literal-final.log`).
- 41 focused compiler/fit/shortfall tests passed (`literal-fit-shortage.log`). These overlap; do not add the counts.
- Exact synthetic connector → compiler → ledger → matching inventory produces a qualified shelf. Different GPU remains incompatible.
- Real isolated PostgreSQL migration/draft-boundary certificate: one test passed, no skipped tests (`literal-pg-cert/results.xml`). Outbound rows unchanged. Disposable database removed by the certificate runner; application databases untouched.
- Restarted only the verified ShopSquire API; current process at this checkpoint: 38212.
- Two zero-retry live manual-acceptance browser cases passed, with and without bounded stretch (`literal-acceptance-browser.log`).
- Live complete-evidence browser gate still FAILED. Terminal reports two accepted claims, missing CPU/GPU/OS/storage type, fetch not attempted, incomplete requirements. Embedded provider evidence reports cached=true and live_allowed=true. This remaining execution/projection discrepancy is not explained by the now-passing connector test and requires tracing the live caller/reconciliation path.

Artifacts are under `C:/AI/ShopSquire-checkpoints/`, outside source commits.

## Not certified

This is not full live product-delivery, all-tab Decision Trace, hosted, recovery, source-review or production WORM certification. No sources were approved, no external messages or payments authorized, and no changes committed. Existing dirty work was preserved.

Next: resolve the remaining live execution/projection discrepancy, then rerun the positive browser gate and all revision-bound trace panels. Do not lower completeness or compatibility authority to make the gate pass. Independent reviews and hosted access still require named human owners and environment access.

## Follow-up: preflight overwrite fixed and dirty-tree verification

The discrepancy above is now resolved. `chat.py` merged every nonempty preflight
fixture field over executed provider evidence, replacing live requirements and
`cached` while retaining `live_allowed`. The merge now fills only missing identity
metadata using `merge_preflight_identity`; executed claims, rejection state,
source, release information and failure state are not replaced.

A stale Celery worker was also restarted, but that alone did not fix this defect.
The causal fix was the preflight merge. No application-specific aliases were added.

Verification after the fix:

- 145 affected backend tests, zero failures/errors/skips (`dirty-consolidated-results.xml`).
- Full frontend suite: 372 tests across 81 files passed (`dirty-full-ui.log`).
- Architecture suite passed; source-size guard passed without ceiling changes.
- Frontend production build and diff whitespace checks passed.
- Ten bitemporal query/ranking tests passed (`dirty-trace-results.xml`). These are not all-tab browser or hosted bitemporal certification.
- Zero-retry live browser batch: three passed, one failed (`reconciled-browser.log`).
  The passes are preflight/live-evidence preservation and acceptance with/without stretch.
- The strict positive-delivery test remains red: **four accepted claims**, `cached=false`,
  `live_allowed=true`; missing **OS and storage type**. The OS source says
  `Windows 10 64-bit`, which is rejected by the manifest. The derived VRAM threshold
  remains rejected pending reviewed policy. CPU/GPU are literal exact predicates,
  not a reviewed desktop/mobile performance-equivalence claim.

The existing dirty changes and assessment documents are preserved; nothing was
committed or pushed. The tree is not claimed wholly green while the positive live
delivery gate remains red. Next work is typed OS/architecture and storage-source
extraction plus reviewed compatibility, not another cached/live workaround.

## Shared-contract hardening follow-up

Executed the next boundary-first work without adding application aliases:

- Requirement section selection preserves original whitespace, so proposed exact
  citations remain substrings of the fetched text.
- Conflicting claims in the same obligation group are all rejected; the first
  encountered claim no longer retains authority. Separate conditions and opposing
  bounds remain separate obligations. Reordered identical alternatives are not
  contradictions.
- An explicitly empty allowed-attribute set rejects all attributes rather than
  acting as an unrestricted scope.
- Failing-first tests reproduced whitespace loss, order-dependent contradiction
  handling, empty-scope bypass and reordered-alternative false conflicts.
- Combined transition, acceptance, shortage, extractor, compiler and projection
  batch: **116 passed**, zero failures/errors/skips (`shared-boundary-batch.xml`).
- Strengthened zero-retry live four-turn browser journey passed in 1.1 minutes
  (`contracts-trace-values.log`). It exercises all registered trace leaves,
  revision history selection, and explicitly compares research counts, revision
  and catalog authority with terminal truth for the research turn. It observes
  no cart-confirm/supplier-send requests. This does not certify every possible
  panel datum or production WORM history.
- Recoverable archive of the 31 modified/untracked source/test/document entries:
  `C:/AI/ShopSquire-checkpoints/shared-contracts-ad65cee4-dirty.tar`.
  It complements base commit `ad65cee4`; no credentials or runtime database/log
  artifacts were included. No changes committed, deleted or pushed.

Still not a complete release: the OS/storage compiler and reviewed equivalence
gaps from the previous live positive-delivery failure remain. Hosted certification,
independent human approvals and recovery/WORM checks are not replaced by these tests.
