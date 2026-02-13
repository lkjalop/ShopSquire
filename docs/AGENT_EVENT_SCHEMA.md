# Agent Event Schema (v1.0)

All trace events emitted via `log_trace_event` include:
- `_schema_version`: `"1.0"`
- `_producer`: source agent/service id
- `_event_type`: event type

Recommended producer fields:
- `idempotency_key` for dedupe-safe event writes
- `tenant_id`
- `trace_id` (already external to payload)

Notes:
- Event IDs are deterministic when `idempotency_key` is provided.
- Events are also mirrored into `event_log` outbox (`type=decision_trace_event`) for async downstream delivery.
