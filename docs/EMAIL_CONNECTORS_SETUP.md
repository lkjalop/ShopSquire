# Email Connectors (Gmail + Microsoft 365) — Setup (MVP)

## Design

- Provider-specific connectors fetch messages and normalize them into the canonical shape used by `evaluate_email_security()`.
- Webhook endpoints only **receive notifications** and enqueue work into Redis.
- A separate worker process fetches the message from Gmail/Graph and calls `evaluate_email_security()` (telemetry + tickets + incidents persistence).

This keeps the “security brain” stable while connector/auth/webhook logic evolves.

---

## Required components

- Redis (required for webhook notification mode): set `REDIS_URL`
- App webhooks:
  - Gmail: `POST /api/v1/ingest/gmail/pubsub`
  - M365: `POST /api/v1/ingest/m365/notifications`
- Connector workers:
  - `python -m src.app.workers.email_connector_worker --provider gmail`
  - `python -m src.app.workers.email_connector_worker --provider m365`

---

## Secrets

Set one shared secret per provider (header `X-Ingest-Secret`):

- `GMAIL_INGEST_SECRET` (or `EMAIL_INGEST_SECRET`)
- `M365_INGEST_SECRET` (or `EMAIL_INGEST_SECRET`)

---

## Gmail (message fetch)

This repo uses plain HTTP OAuth (no Google SDK dependency).

Choose ONE:
- **Access token**: set `GMAIL_ACCESS_TOKEN`
- **Refresh token**: set `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`

Worker env:
- `GMAIL_USER_ID=me` (default)

Webhook mode notes:
- Real Gmail push notifications provide `emailAddress` + `historyId`.
- MVP worker currently supports queue items that include a `message_id` directly.
  - For full Gmail “watch/history” behavior, we’ll add history-based fetching next.

---

## Microsoft 365 (Graph message fetch)

Choose ONE:
- **Access token**: set `M365_ACCESS_TOKEN`
- **Client credentials**: set `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET`

Worker env:
- `M365_MAILBOX=<shared-mailbox-email>` (required, e.g. `accounts-payable@yourcompany.com`)

Webhook validation:
- Graph subscription validation calls `POST /api/v1/ingest/m365/notifications?validationToken=...` and expects the token echoed.
- Optional verification of Graph `clientState`: set `M365_CLIENT_STATE`.

---

## Viewing results

Admin APIs (owner/developer):
- `GET /api/v1/admin/email_security/suppliers`
- `GET /api/v1/admin/email_security/incidents`

Metrics:
- `/metrics` includes email verdict + ticket + dedupe + connector counters.

