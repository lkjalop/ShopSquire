# PowerBI Exports & SLA

## Exports
- Endpoints in `src/app/routers/admin.py`:
  - `/api/v1/admin/powerbi/dataset` – JSON snapshot (decisions, orders, security).
  - `/api/v1/admin/powerbi/export.csv` – unified CSV with pagination (`limit`, `offset`) and filters.
  - `/api/v1/admin/powerbi/export.ndjson` – NDJSON stream with pagination and filters.
  - `/api/v1/admin/powerbi/export.zip` – zipped CSVs for decisions/orders/security.

### Pagination Guarantees
- All export endpoints enforce `limit` and `offset` bounds; defaults ensure safe memory use.
- Filters validate ISO timestamps and statuses to avoid malformed queries.

### Schema Versioning Notes
- Current CSV/NDJSON schemas are documented inline in responses; versioning can be added via an `X-Schema-Version` header.
- For downstream BI consumers, pin versions in integration configs and track changes via release notes.

## SLA Targets (suggested)
- Export Latency: p95 < 500ms for `limit<=2000` on Postgres.
- Availability: 99.9% monthly for read-only exports.
- Integrity: zero data loss in nightly retention windows.
