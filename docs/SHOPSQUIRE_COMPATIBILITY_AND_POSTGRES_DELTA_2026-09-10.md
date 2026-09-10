# Compatibility and PostgreSQL delta — 2026-09-10

Status: local engineering verification, not complete buyer-delivery or production certification.

## Repairs executed

1. `accepted_catalog_projection.py::_verdict` now delegates typed comparisons to the shared registry instead of treating substrings as compatibility. Exact alternatives, upper bounds, invalid numeric values, unsupported operators and boolean/number confusion have regressions. This does not infer relative CPU/GPU performance.
2. The model extractor now rejects textual values absent from its quoted span. A real quotation alone cannot validate an invented CPU/GPU identity attached to it.
3. Fresh derived product observations no longer gain independent verification merely from freshness. Their values and derivation labels remain visible pending reviewed provenance.
4. The scope revision hash includes derivation policy. Changing that policy invalidates old pins; hashing is not approval to execute a rule.
5. The old PostgreSQL runner silently entered SQLite test isolation. The replacement runs a narrow explicit PostgreSQL certificate outside that conftest, checks the actual dialect/database/migration head, rejects skipped required tests, restores environment variables and removes only its own uniquely named disposable container.

## Verification

- Eight initial exact-comparison regressions failed before repair; later boolean controls also pass.
- Both invented-model-value regressions failed before repair.
- Fresh-derived verification and derivation-revision regressions each failed before repair.
- Compiler/projection/model-extraction/sourcing/audit/architecture batch: 154 passed, zero failures or skips.
- Scope/projection/model/research-outcome follow-up: 57 passed.
- Real PostgreSQL 16 migration to Alembic head succeeded in an isolated loopback-only container, not the unrelated project on port 5432.
- PostgreSQL durable sourcing test: explicit acceptance persists an internal draft across sessions, replay is idempotent, and neither outbound_message nor outbound_delivery_job gains a row. The repaired runner passed this test with zero skips. This is a handler/database certificate, not a browser shortage or supplier-network certificate.
- Browser four-turn/all-15-panel regression passed with zero retries after the comparison repairs (1.1 minutes). It is a continuity/trace regression, not a complete CPU/GPU positive-delivery certificate.
- Local WORM tests use controlled providers. They do not verify deployed cloud retention or deletion denial.

Artifacts: `C:/AI/ShopSquire-checkpoints/*20260910*`, including `pg-runner-20260910/results.xml`. The manually created `shopsquire-cert-20260910` database container is stopped and retained; the runner-created disposable container was removed. No application database was deleted.

## Remaining gates, in order

1. Establish independently reviewed, scoped CPU/GPU equivalence rules with exact identities, rule versions, provenance and expiry/revocation. No source or rule was signed off by this run.
2. Bind reviewed rules and complete literal requirements through the live fit path; prove a non-empty qualified shelf against actual matching inventory. Do not use RAM/VRAM sufficiency as full compatibility.
3. Browser-test budget shortage separately from stock shortage, then explicitly accept a draft; inspect durable queues and transport records. The off-catalog PostgreSQL certificate is only one portion of this gate.
4. Publish reviewed cross-category manifests to the database, including packaging/unit semantics; finish the large orchestration extraction. Neither was completed here.
5. Supply an authorized hosted test destination and independent reviewers. Repeat deployment/failure-injection checks there and verify actual WORM retention/immutability. Local PostgreSQL is not hosted certification.

Independent review and hosted access were requested. No supplier send, source approval, equivalence approval or remote push occurred.
