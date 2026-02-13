# Decisions Read Policy

This policy defines endpoint behavior when `DECISION_LOG_WRITES_ENABLED` is disabled.

## Graceful user-facing endpoints (HTTP 200)
- `GET /api/v1/decisions/summary`
- `GET /api/v1/decisions/stream`
- `GET /api/v1/decisions/latest`
- `GET /api/v1/decisions/{trace_id}`
- `GET /api/v1/decisions/{trace_id}/query`

These return a stable payload with:
- `available: false`
- `reason: "decision_reads_disabled"`

## Explicit engineering/admin endpoints (HTTP 501/403)
- `GET /api/v1/decisions/query`
- `GET /api/v1/decisions/{trace_id}/explain`
- `GET /api/v1/decisions/{trace_id}/replay`

These return explicit errors to surface environment/configuration state during debugging.

## Rationale
- User-facing surfaces should remain resilient and avoid hard errors.
- Admin/debug surfaces should fail explicitly when decision reads are disabled.
