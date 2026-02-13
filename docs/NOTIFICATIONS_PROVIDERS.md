# Notifications Providers (SES/Twilio)

This project supports optional email/SMS sending for demo purposes. Keep secrets in environment variables or a secure secret manager.

## Amazon SES (Email)

Environment variables:
- `SES_ENABLED=1` — enable SES sender
- `SES_REGION=us-east-1` — AWS region
- `SES_SENDER_EMAIL=no-reply@example.com` — verified sender address
- `AWS_ACCESS_KEY_ID=...` — access key (or use instance/profile creds)
- `AWS_SECRET_ACCESS_KEY=...` — secret key

Notes:
- Verify the sender domain/address in SES.
- In sandbox mode, verify recipient addresses or request production access.
- When `SES_ENABLED` is not set, the service logs dispatch intent to `decision_logs` without sending.

## Twilio (SMS)

Environment variables:
- `TWILIO_ENABLED=1` — enable SMS sender
- `TWILIO_ACCOUNT_SID=...`
- `TWILIO_AUTH_TOKEN=...`
- `TWILIO_FROM_NUMBER=+1234567890`

Usage:
- When enabled, the SMS sender will attempt to send transactional updates (e.g., case created). Otherwise, intents are recorded to `decision_logs` and skipped.

## Security & Compliance

- Prefer short-lived credentials via a secrets manager; avoid hardcoding.
- Log only metadata in `decision_logs` (no message bodies beyond what is necessary for audit).
- Respect customer opt-in preferences and per-tenant policy flags.

## Local Testing

- Set the env vars above and run the API; verify logs show provider health.
- For SES, use AWS CLI or console to confirm sends; for Twilio, check the dashboard.
