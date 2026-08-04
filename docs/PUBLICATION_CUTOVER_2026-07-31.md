# ShopSquire publication cutover

## Decision

Treat `agent/platform-reliability-publication-20260730` and draft PR #7 as the
non-destructive preservation/cutover record. Do not merge its 1,217-commit diff
into the stale default branch as an ordinary feature PR.

The remote default branch is `wip/docker-real-env-20260213`. At assessment time,
the publication branch is 1,217 commits ahead, zero behind, with merge base
`45a574055f3fa722fd80b91f0c64a9273e0e34bd`. A normal line-by-line review would
misrepresent both the risk and the current architecture.

## Trusted candidate

The last fully hosted proof anchor is `396476f0`. Its production-shaped and V2
workflow runs completed successfully with retained artifacts. The following
reviewable commits sit above that anchor:

1. `cf77740b` — governed supply-exposure coverage.
2. `72e4275b` — authoritative Party references for communication observations.
3. `49821c80` — tenant-scoped shadow-pilot outcome scorecard.
4. `440ca45b` — finalized V2 route-authority seam.
5. `1d4f6274` — privacy deletion orchestration and temporary-chat isolation.

The current candidate becomes a trusted cutover base only after those five
commits pass hosted migration, service, worker, frontend, and browser gates.

## Cutover sequence

1. Keep PR #7 as a draft preservation PR and CI evidence surface.
2. Require green hosted checks for the candidate commit; retain migration,
   worker, browser, and security artifacts.
3. Obtain a maintainer decision to replace the stale default with a protected
   `platform/v2-current` branch at the proven candidate commit. Do not force-push
   the existing default.
4. Preserve the old default as a named archival branch/tag before changing the
   repository default.
5. After the default changes, open topic PRs from the new base. Initial topics:
   supply exposure, Party/communication authority, outcome measurement, routing
   authority, and privacy/session isolation.
6. Enable branch protection and require the hosted proof workflow before any
   topic PR can merge.

## Explicit exclusions

The following local changes are not part of the cutover candidate and must not
be staged implicitly:

- `config/feature_flags.json`
- `config/security/cv_playbooks.json`
- local proof artifacts, screenshots, SQLite WAL files, Celery schedules,
  scratch material, and unreviewed documents.

## External evidence gates

The cutover does not certify business lift. Independently reviewed relevance
labels and a tenant-authorized shadow dataset remain separate external-authority
gates. Neither may be self-sealed from repository code or synthetic replay.
