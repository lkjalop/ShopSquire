# Bounded roadmap checkpoint and runtime isolation

Item 0 is complete for the local fictional-shop execution baseline. This does not
close the independent-environment, remote CI, rollback or endurance gates in item 12.

The recoverable source checkpoint is
`C:/AI/ShopSquire-checkpoints/20261001-roadmap-source.zip`: 5,079 source,
configuration, migration, test and documentation files. Its per-file SHA-256
manifest was verified after extraction to `20261001-roadmap-restore`. Secrets,
runtime databases, binary assets and installed dependencies are deliberately
outside this source archive. The earlier pre-continuity checkpoint retains a
database backup. Ongoing edits remain in the working tree and need a subsequent
checkpoint when the next batch is stable.

The restored copy imported its own modules, migrated a new SQLite database through
revision 88, passed 19 focused tests, and started on port 8088 with HTTP health 200.
That owned server was stopped after verification. It reused the installed Python
environment: this is source restoration, not a second-environment installation.
Evidence is in `.artifacts/roadmap-execution-2026-10-01/restore-tests.xml`,
`restore-migrations.log` and `restore-health.json`.

The acceptance cases are frozen in `config/benchmarks/roadmap_acceptance_v1.json`.
Market and forecast fixtures have fixed scopes, seeds and time cutoffs; benchmark
reports record input fingerprints. Changing a case requires a new version and an
explicit explanation rather than silently weakening a failed assertion.

Start the bounded local backend with:

```powershell
$env:APP_ENV='local'
$env:DATABASE_URL='sqlite:///C:/AI/ShopSquire/.artifacts/connected-shop-2026-09-28/shop.sqlite3'
$env:DATABASE_URL_RO=$env:DATABASE_URL
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/seed_operator_inventory_demo.py
./scripts/start_isolated_roadmap_backend.ps1 -EnableExpiry
```

The startup script refuses an occupied port and records its effective environment.
It binds loopback, uses an isolated database for reads and writes, selects sandbox
supplier transport, disables external research and unrelated workers, and bounds
chat/upstream/research timeouts. The new stock-operation endpoints additionally
require enabled demo routes, a synthetic tenant and authenticated enrolled people.
They never call payment or external messaging providers. Real supplier transport
remains blocked by the existing approval-required transport implementation.

Main isolated database migrations through revision 89 and the operator fixture
seed succeeded. A fresh backend using the startup script passed the independent
person receipt/transfer browser test. Artifact: `operator-browser-v2.json`.
No production deployment or real commerce was performed.

## Final batch checkpoint

The current code checkpoint is
`C:/AI/ShopSquire-checkpoints/20261001-roadmap-64pct-v2.zip` (5,134 files), with a
consistent SQLite backup at the same basename plus `.sqlite3`. Backup integrity
is `ok` and the database is at revision 91. The sibling `-receipt.json` records
the source and database SHA-256 hashes. The first `64pct` archive excluded some
source files whose names contain “secret”; v2 corrects the filter to retain code
while excluding credential data. Use v2 for restoration.

Extraction to `20261001-roadmap-64pct-restore` verified all file hashes and
confirmed imports came from that restored tree. Fresh migrations through 91 and
61 focused regression tests passed. A restored-copy server started on loopback
8088 and returned HTTP 200 from `/health`; it was then stopped. Health reported
Redis fallback, so this proves source startup, not healthy Redis or full service
readiness. Persisted case-memory browser checks use the database and remain
separate from Redis-dependent session features.

Artifacts: `final-restore-receipt.json`, `final-restore-tests.xml`,
`final-restore-migrations.log`, `final-restore-startup.json` and
`final-restore-startup.log` under `.artifacts/roadmap-execution-2026-10-01/`.
This reused the existing Python environment and does not close item 12.
