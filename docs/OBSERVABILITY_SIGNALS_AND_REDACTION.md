# Observability Signals & Redaction Policy

This document defines which signals are emitted externally (Splunk/Datadog) and which remain private, and outlines the redaction/sanitization rules applied before emission.

## Signals

- External (sanitized):
  - `decision_event` summaries: agent name, action, policy version, severity.
  - `iam_activity`: authn/authz outcomes, path/method, allowed roles, risk tags.
  - `email_security`: DMARC aggregate summary (counts, fail rate, top sources), severity.
  - Operational: Prometheus metrics (/metrics) via Grafana/Datadog visualization.

- Private (internal only):
  - Full decision `input_data` and `retrieved_context` bodies.
  - Raw email contents, attachments, and headers.
  - PII beyond hashed identifiers (e.g., full emails, customer IDs).

## Redaction Rules

- Use `src/app/observability/redaction.py`:
  - `security_sanitize`: scrub PII, normalize unicode.
  - `redact_for_trace`: remove bulky/blobby fields and base64-like payloads.
  - `hash_fields`: replace sensitive identifiers (e.g., `email`, `actor_id`, `resource_id`) with SHA-256 short hashes.

## Emission

- Use `telemetry_emit(event, severity, sourcetype)` for all external signals.
  - Env-gated sinks: Splunk HEC (`SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN`), Datadog (`DD_API_KEY`, `DD_SITE`).
  - Falls back to local logging; never raises into app flows.

## Supply-Chain IoC Tags

- Use `src/app/observability/ioc.py:add_ioc_tags(event)` to derive minimal tags:
  - `ioc:typosquat` on suspicious package names.
  - `ioc:prerelease` when pre-release versions are observed.
  - `ioc:external_source` for non-standard external URLs.

## RBAC & Dashboards

- Admin analytics are RBAC-protected and proxy Grafana securely.
- Splunk dashboards should ingest sanitized events; verify ingestion via CI step and dev script.
