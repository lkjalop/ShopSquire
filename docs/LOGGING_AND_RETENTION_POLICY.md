# Logging & Retention Policy (Scaffolding)

This document describes the intended logging/retention posture for ShopSquire and the initial feature flags to control it. It separates immutable audit evidence from ephemeral/debug content, applies PII redaction by default, and supports stricter regional controls (e.g., EU/EEA).

## Objectives
- Provide audit-grade, tamper-evident decision evidence (minimal but sufficient).
- Keep storage lean: minimize raw content; prefer hashes, IDs, and references.
- Default-safe privacy: redact PII, limit retention, and enforce geo-specific constraints.

## Evidence Model
- Immutable (kept):
  - `decision_id` (UUID), timestamps, `agent_name`, `policy_version`, `controls_applied`.
  - Input/output digests (HMAC-SHA256 with server-secret salt), not raw content.
  - Key signals (presence of): severity, risk score, tags (MITRE/OWASP/DREAD/KEV/CVSS) — avoid raw payloads in immutable records.
  - Linkage: `trace_id`, optional `approval_id`, feature-flag versions.
- Ephemeral (cleared/rotated):
  - Raw prompts, free-text, and tool parameters that may contain PII — keep only redacted/hashed summaries.
  - Intermediate LLM/system artifacts — summarize into short rationales and discard after TTL.

## PII Redaction & Minimization
- Redact on ingress for logs: emails, phones, SSNs, card numbers, addresses, IPs.
- Prefer coarse geolocation (ISO country code) and discard raw IPs after derivation.
- Tokenize identifiers (e.g., customer IDs) and keep mapping in a short-lived, access-controlled vault.

## Regional Controls & Retention
- Geo enforcement (EU/EEA):
  - Use GeoIP to derive region; enforce stricter defaults for EU.
  - Retention: shorter by default; non-essential logs disabled or minimized.
- Suggested tiers (defaults):
  - Security events: 90 days (EU: 30 days). Archive daily hashed summaries up to 1 year if needed.
  - Decision logs (immutable, minimal data): 30–90 days (EU: shorter). No raw content.
  - Raw traces: 7–14 days max (EU: ≤72 hours) or disabled; always redacted.
- Data subject requests: Support deletion/anonymization of non-essential logs; rotate token mappings.

## Feature Flags (config/feature_flags.json)
- `LOG_DETAIL_LEVEL`: `minimal` | `standard` | `debug` (default `standard`)
  - Drives how much context is persisted (debug reserved for non-prod).
- `LOG_PII_REDACT`: true | false (default true)
  - Redact PII tokens in any persisted record.
- `SECURITY_EVENT_PERSIST_CONTENT`: true | false (default false)
  - When false, store only hashes/IDs/tags for security events (no raw content).
- `GEO_ENFORCE_PRIVACY`: true | false (default true)
  - Enforce EU/EEA stricter retention and detail limits when user is in the region.
- `LOG_RETENTION_DAYS_DEFAULT`: number (default 90)
- `LOG_RETENTION_DAYS_EU`: number (default 30)
- `DECISION_LOG_WRITES_ENABLED`: true | false (existing)

## UX & Admin
- Customer UI: No trace by default. On blocks, show short, neutral guidance and optional support link.
- Dev/Privileged-only panel: A small Gear reveals a compact trace snapshot; deep signals (MITRE/OWASP/DREAD/KEV/CVSS) are hidden behind a single drilldown with a Copy JSON button.
- Admin Live Ops (`/ui/status`): Full decision/security timelines and approvals; preferred place for investigations.

## Implementation Notes (initial scaffolding)
- Services should read flags via `load_feature_flags()` and:
  - Apply redaction before persistence when `LOG_PII_REDACT`.
  - Avoid persist content when `SECURITY_EVENT_PERSIST_CONTENT` is false (store hashes/tags only).
  - Honor `LOG_DETAIL_LEVEL` to downgrade detail in non-essential logs.
  - Use GeoIP-derived country to apply EU retention/detail limits when `GEO_ENFORCE_PRIVACY`.
- Integrity: Consider daily chain hashing (Merkle root) or WORM storage for immutable records.

This document will evolve as we wire each router/service to the flags above.

## Trace redaction (local default)

- Decision trace payloads are sanitized and redacted at write?time in `src/app/services/decision_log.py`.
- Large blobs (base64 images, file bytes) are replaced with `[REDACTED_BLOB]` or `[REDACTED_BASE64]`.
- Long text values are replaced with `[REDACTED_LEN:...]` when exceeding 512 chars.
- PII (email/phone/SSN/IP/API keys) is scrubbed using `src/app/deps.py`.

This keeps trace integrity while minimizing sensitive data exposure for GDPR/EU AI Act alignment.
