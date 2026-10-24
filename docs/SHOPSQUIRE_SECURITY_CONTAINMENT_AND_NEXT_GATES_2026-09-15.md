# ShopSquire security containment and next gates — 15 September 2026

## Outcome

Confirmed security defects were repaired and loaded into the main local API on port 8080 and the isolated review API on 18082. This is a tested containment change, not a claim that the whole repository is production-ready. The six-step roadmap remains partly complete. No public push or history rewrite was performed.

## Recovery and publication

- Restricted-access, AES-256-GCM encrypted backup of all Git refs and the initial tracked/untracked nonignored worktree: 5,346 files. An actual bare clone and full `git fsck` passed; archive contents matched their SHA-256 manifest.
- Separate encrypted backup of the main running SQLite database, process environment/command and ignored root `.env`. SQLite integrity and encryption round-trip checks passed before migrating/restarting the API.
- Backup location: `C:/AI/ShopSquire-checkpoints/security-20260915`. Recovery keys are separate files under that restricted directory; they are not in the repository. An off-device copy still needs a private destination. Store recovery keys separately from that copy.
- Original recovery bundles are retained. A post-fix worktree bundle is prepared separately under `post-fix`.
- Gitleaks 8.30.1 was downloaded from the official release and checksum-verified. All-ref history scan: 1,899 commits processed, 27 findings. Classification: 25 documented local/demo credentials, placeholders or synthetic detection/idempotency fixtures; two captured incident capability tokens.
- The captured tokens were removed from the current golden fixture. Neither matched an active token in the main runtime Redis or token-file store. This check does not prove absence in other deployments; historical copies still exist.
- Current publication snapshot: approximately 42.5 MB of scanned content; 24 remaining Gitleaks findings are the documented fixture/example cases. No blanket suppression was added. This is a scan with reviewed findings, not a zero-findings scan.
- Card-number scanner passed on the publication snapshot. Pattern scans do not establish that all documents, screenshots, dependencies, ignored files or historical artifacts are free of sensitive content. Broader artifact review and an explicit publishable checkpoint remain release gates.
- Public GitHub is not the private backup destination. Finish off-device recovery and artifact/publication review before uploading this large accumulated worktree.

## Security changes and wiring

| File | Change |
|---|---|
| `src/app/security/auth.py` | Verify bearer identity before using subject/email; fingerprint credentials in audit events; unknown/unset environment does not enable known local keys. |
| `src/app/security/admin_route_boundary.py`, `src/app/main.py` | Apply baseline authorization after admin API registration, retaining narrower route guards. |
| `src/app/routers/admin_dmarc.py` | Authenticated, read-only summary; caller thresholds cannot trigger SIEM writes. |
| `src/app/routers/merchant_dashboard.py`, `admin_email_security.py` | Remove automatic owner-key cookie and hardcoded JavaScript credential fallback. Email lab requires owner authorization and explicit local environment. |
| `src/app/routers/escalation_room.py` | Unknown environment fails closed; Host headers cannot establish a local peer. |
| `src/app/services/operator_tenant_membership.py` | Unknown environments default to strict tenant membership. |
| `src/app/services/dmarc_ingest.py`, `dmarc_schema.py`, `src/app/routers/dmarc.py` | Tenant-owned portable storage; bounded ZIP input and DTD rejection; enforce date windows and message-weighted rates; missing measurements stay null; ingestion runs off the async request loop. |
| `alembic/versions/20260876_dmarc_tenant_boundary.py` | Add tenant ownership; leave legacy unowned rows unassigned and invisible to tenant queries. |
| `src/app/services/terminal_qualification.py` | Count only exact qualified configurations; replace stale questions only for the matching workload identity. |
| `src/app/services/terminal_research_narration.py`, `terminal_research_reconciliation.py`, `research_outcome.py` | Partial/unknown authority cannot preserve positive qualification prose or release catalog candidates. |
| `src/app/services/turn_transition.py`, `src/app/routers/chat.py` | Persist the same terminal narration and remaining question obligations used by chat. |
| `src/app/services/market_signal_adapters.py` | Start SQLite outer transaction before savepoints so rollback removes staged ingestion. |
| `src/app/services/market_pipeline.py` | Separate pending/failed/committed receipts; secondary history starts after canonical commit. |
| `src/app/services/fulfillment/transport.py`, `outbound_queue.py` | Foreground and queued SMTP delivery are held pending verified independent-person approval. |
| `src/app/services/bi_intelligence.py`, `src/app/routers/admin_bi.py` | Move metric classification into the BI service, resolving router-size growth without raising the limit. |
| `.github/workflows/ci.yml` | Explicitly run the new security, DMARC, terminal-truth, market and transport regressions. |
| `tests/golden/suggest_corpus/compare_two_models.json` | Remove captured incident access tokens. |

Migration 75 (the preceding evaluation repair) and migration 76 were applied to the backed-up main runtime. Existing unrelated working-tree changes were preserved.

### Supplier sending: containment versus completed approval

Configured SMTP sends now fail with `independent_person_approval_required`, including queued sends. They do not silently become sandbox sends or record a successful real transmission. Explicit sandbox demonstrations still work. The SMTP adapter remains unit-testable with injected clients.

This is a deliberate hold, not the completed two-person approval system. Before lifting it, bind the initiator and approver to distinct verified human subjects with active membership in the same tenant; bind approval to the exact draft hash, recipient, attachments, case and version; expire/revoke it; and recheck it at queue dispatch. Shared role keys, arbitrary user IDs, unverified JWT payloads and historical audit identities are insufficient. Other supplier channels require the same review before use.

## Verification and what green means

| Gate | Evidence |
|---|---|
| Focused backend security and regressions | 94 passed. Covers forged/valid identity, admin registration, DMARC tenant/window/XML/ZIP boundaries, terminal truth, market rollback, supplier transport and queue behavior. |
| PostgreSQL | 5 passed against the isolated PostgreSQL instance, including tenant binding, existing release integrity checks and new DMARC ownership/weighted aggregation. |
| KCD2 browser | Playwright clickthrough passed: partial requirements, blocked catalog authority, zero qualified products, remaining OS obligation, matching chat and persisted turn narration, visible terminal answer. This is isolated-runtime certification, not proof of a real-product cohort. |
| Main runtime containment | Health 200; unauthenticated DMARC summary and email lab 401, without credential cookies. Same checks pass on the isolated API. |
| Source checks | Async database checker and source-size guard pass; oversized-file warnings remain. The BI helper extraction removes the previously reported three-line growth violation. |
| Scope | Focused checks, not a complete application-wide test sweep. Existing Pydantic/telemetry warnings remain. Remote CI and branch protection have not been observed passing for this uncommitted change. |

Tests added or extended include `tests/security/test_publication_security.py`, `test_dmarc_boundaries.py`, `tests/services/test_terminal_qualification_security.py`, `test_market_pipeline.py`, `test_terminal_research_narration.py`, `test_terminal_research_reconciliation.py`, `tests/services/fulfillment/test_transport.py`, `test_transport_health.py`, `tests/chaos/test_release_integrity_postgres.py`, and `frontend/e2e/live-unresolved-purchase-boundary.spec.ts`.

Local receipts and logs are under `C:/AI/ShopSquire-checkpoints/security-20260915`: `final-security-suite.log`, `postgres-security.log`, `kcd-final.log`, `live-security-final.json`, `history-triage.json`, `capability-revocation.json`, and backup receipts. Do not publish private triage, environment or recovery-key files.

## Roadmap and priority

| Order | Current status | Required green |
|---|---|---|
| 1. Private recoverable backup and containment | Local recovery verified; main API patched; off-device destination pending. | Restore encrypted worktree/runtime backup on another device; verify key recovery and database integrity. |
| 2. Secret/history/artifact review, then publication | History and source-pattern findings reviewed; captured tokens removed; publication not performed. | Review remaining document/log/image artifacts; record exact accepted fixture findings; verify token inactivity in other deployments; create a reviewable checkpoint; run remote CI; then publish. |
| 3. KCD2 terminal truth | Corrected with backend and live browser regression. | Keep one terminal authority/count/question contract across chat, case read model, trace and shelves. Extend adversarial cases to changed revisions and delayed responses. |
| 4. Small real product cohort | Still open. No synthetic catalog item counts as real product evidence. | Start with 1–3 exact configurations: manufacturer SKU/MTM, CPU/GPU including laptop variants, RAM, storage, OS, region, dated price/stock, source receipts and independently reviewed equivalence. Exercise qualified and correctly refused outcomes. |
| 5. Independent-person approval | Real SMTP held; positive approval workflow still open. | Distinct verified people; same-tenant membership; exact draft binding; same-person/shared-key/stale/revoked/tenant-mismatch denial; dispatch-time revalidation and duplicate-worker protection. |
| 6. Discovery, durability and shadow testing | Canonical market rollback/commit receipts repaired. Discovery and durable secondary history remain open. | Canonical URL dedup preserving distinct source versions; publisher authority ordering; durable/idempotent secondary-history outbox; crash/retry/race tests; shadow runs proving zero operational writes or sends. |

### Recommended architecture hierarchy

1. **Authentication and tenant ownership** establish who may act and whose data is visible.
2. **Source/evidence ledger** records provenance, timestamps, accepted/held/rejected claims and missing obligations.
3. **Qualification reducer** produces one immutable result for an exact case revision and exact product configuration.
4. **Read projections** render that result in chat, trace, shelves and admin panels without inventing a second conclusion.
5. **Approval and action boundary** binds verified people to exact irreversible actions.
6. **Durable dispatch and observation** use transactional records, idempotency and recovery receipts; shadow analysis stays outside operational actions.

The next useful expansion is the small real evidence-complete cohort. Parallel stage scheduling, wider autonomy and more connector breadth should wait for these boundaries. The SQLite failure demonstrates why a successful helper return does not prove rollback or durability.

## Supporting references

The reproduced savepoint behavior is documented in [SQLAlchemy’s SQLite transaction guidance](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#legacy-transaction-mode-with-the-sqlite3-driver). XML controls address the threat classes described in [Python’s XML security guidance](https://docs.python.org/3/library/xml.html#xml-vulnerabilities). Secret scanning used the [official Gitleaks project](https://github.com/gitleaks/gitleaks). These references explain the controls; local test receipts are the implementation evidence.
