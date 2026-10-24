# Browser CI profiles and migration inspection

The independent repair checkout now uses the committed API/test export for browser/worker jobs that do not require a model runtime. The full default installer remains available for the suites that require it. A new clean Windows Python installation of this export passed installation, `pip check`, export consistency and compilation; the lock SHA-256 is `1949942a0040db095a3685b7baa749ea654eac097ea230eae4183180bf1435cc`.

The UI workflow previously invoked Playwright in a Vitest component directory with no Playwright configuration. It now runs the configured component runner and retains the Python browser suite. Both frontends, matching Python Chromium and the native OCR/barcode dependencies are installed explicitly. The procurement workflow uses Node 22 and checks actual migration heads instead of a hard-coded historical revision. These changes do not turn remaining browser/security failures or skips into passes.

Native PostgreSQL inspection exposed an untested migration defect: `alembic current` had no destination revision, but entered the downgrade planner and raised `KeyError`. Four new controls reproduced four failures. Read-only inspection now bypasses only that absent-destination plan; ordinary downgrade plans retain their data-preservation checks. Populated communication/approval history is checked before destructive steps start. The upgrade tests name the intended historical rollback target rather than assuming a fixed number of tail revisions.

Validation on the independently assembled cohort:

- **66 passed, no failures/errors/skips:** routing/cart regressions, migration/restore/history controls and email lab actor/security checks, including a CI-style `APP_ENV=testing` parent profile with explicitly local lab tests.
- **Three admin browser cases and one storefront browser smoke passed** in the new API/test environment. Two admin scenarios mock API responses; these are rendering/contract checks, not live incident-provider qualification. The lab HTML tests retain all prior content/CSP/CSRF expectations and now provide an actual loopback peer, owner identity and explicitly local environment.
- A disposable native pgvector/PostgreSQL database passed fresh upgrade, current-head inspection, an empty-tail downgrade, rejection of the incomplete head state, re-upgrade and final current-head inspection. Its owned container was removed. This is schema recovery, not populated production-provider restoration.
- Both unchanged size ratchets and changed-file Ruff pass. Actionlint **v1.7.12** validates the four changed browser workflows; ShellCheck/Pyflakes were not installed or run. The downloaded actionlint archive was checked against the release's SHA-256 list.

The earlier native run failed after upgrade at read-only inspection and is retained. This cohort's local browser and PostgreSQL results do not certify hosted Linux execution or the full CV corpus/model stack. Private receipts use the `implementation-20261024-browser-ci-*`, `implementation-20261024-migration-current-*` and `browser-ci-migrations-v2` names.
