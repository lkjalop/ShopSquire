# Event Log MVP & Outbox

Purpose: provide a single, durable event stream for decisions, audits, and security events with an outbox pattern for reliable delivery.

## Schema
- `event_log`
  - id: TEXT PK
  - type: TEXT (e.g., 'decision.created', 'decision.audit', 'security.escalated')
  - payload: TEXT (JSON string)
  - status: TEXT DEFAULT 'pending' ('pending'|'sent'|'error')
  - delivery_url: TEXT NULL
  - created_at: TEXT DEFAULT CURRENT_TIMESTAMP
  - last_attempt: TEXT NULL

## Write Path
- Decision persistence functions write to `decision_logs` and `decision_audits` within a transaction.
- Emit corresponding `event_log` rows as part of the same transaction.

## Delivery
- A background dispatcher (future work) reads `pending` events and attempts delivery (webhook/SIEM). Updates `status` and `last_attempt`.
- Idempotency via `id` and external correlation keys in payload.

## Migration Plan
- Start with SQLite/JSON string payloads.
- Evolve to Kafka topic(s) for multi-tenant at scale.
