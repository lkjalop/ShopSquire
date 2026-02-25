# Security Hardening Runbook

## Purpose
Operational guide for the current security hardening controls:
- External audit anchoring
- Celery message/queue hardening
- Metrics exposure restrictions
- Redis ACL wiring
- Internal mTLS defaults
- LLM10 model-theft detection tuning
- QR redirect-chain controls
- Export DLP enforcement

Reference env template: `config/security/security-hardening.env.example`.

## 1. Audit External Anchoring
Set:
- `AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE=worm_local|notary_http|both`
- `AUDIT_CHAIN_WORM_ARCHIVE_PATH`
- `AUDIT_CHAIN_NOTARY_URL` (if using notary)
- `AUDIT_CHAIN_ANCHOR_HMAC_KEY`

Deploy notes:
- Mount WORM/object-lock capable volume for the archive path.
- Restrict write access to app identity only.

Validation:
1. Trigger an audited event.
2. Call `GET /api/v1/admin/compliance/reports/audit-chain/verify`.
3. Confirm `external_anchor.mode` and anchor health in response.

## 2. Celery Queue and Signing Controls
Set:
- `CELERY_QUEUE_PREFIX=shopsquire`
- `CELERY_TASK_SIGNING_ENABLED=1` for signed mode
- `CELERY_SECURITY_KEY`, `CELERY_SECURITY_CERTIFICATE`, `CELERY_SECURITY_CERT_STORE`

Deploy notes:
- Ensure workers and producers share trust store.
- Rotate cert/key with overlap window.

Validation:
1. Enqueue swarm job.
2. Confirm it routes to namespaced queue (`shopsquire.swarm`).
3. In signing mode, verify workers process signed tasks only.

## 3. Metrics Exposure Controls
Set:
- `METRICS_INTERNAL_ONLY=1`
- `METRICS_REQUIRE_AUTH=1`
- `METRICS_ALLOW_CIDRS=<internal CIDRs>`

Ingress recommendations:
- Keep `/metrics` behind private network or auth gateway.
- Do not expose `/metrics` publicly.

Validation:
1. Request `/metrics` from disallowed IP -> expect `403`.
2. Request `/metrics` without auth (non-local) -> expect `401`.
3. Request with owner/developer auth from allowed CIDR -> expect `200`.

## 4. Redis ACL User Wiring
Configure ACL file `config/redis/users.acl` with real passwords.
Set app env:
- `REDIS_ACL_USERNAME=shopsquire_api`
- `REDIS_ACL_PASSWORD=<api password>`

Deploy notes:
- Use separate users for app, celery, observability.
- Remove broad `+@all` access from production users.

Validation:
1. App health and Redis-dependent features remain functional.
2. Redis `ACL LIST` shows scoped key patterns and command sets.

## 5. Internal mTLS by Default
Set:
- `INTERNAL_MTLS_REQUIRED=1`
- `INTERNAL_MTLS_PATH_PREFIXES` as needed
- `INTERNAL_MTLS_ALLOWED_FINGERPRINTS` for cert pinning

Proxy requirements:
- Forward headers:
  - `X-SSL-Client-Verify`
  - `X-SSL-Client-Fingerprint`
  - `X-Forwarded-Client-Cert`

Validation:
1. Internal protected route without mTLS headers -> `401`.
2. With invalid fingerprint when allowlist set -> `403`.
3. With valid cert/fingerprint -> success.

## 6. LLM10 Model-Theft Controls
Set/tune:
- `MODEL_THEFT_MAX_EXTRACTION_REQ_PER_HOUR`
- `MODEL_THEFT_MAX_IDENTICAL_QUERY_PER_HOUR`
- `MODEL_THEFT_MIN_SAMPLES_FOR_DIVERSITY`
- `MODEL_THEFT_MIN_UNIQUE_FP_PER_HOUR`

Validation:
1. Repeated extraction-like prompts -> blocked with structural reason.
2. Check incident ticket/event generation for blocking reasons.

## 7. QR Redirect-Chain Controls
Set:
- `QR_REDIRECT_RESOLUTION_ENABLED=1`
- `QR_REDIRECT_MAX_HOPS=5`
- `QR_REDIRECT_TIMEOUT_SEC=2.0`

Validation:
1. Submit CV image with redirecting QR URL.
2. Confirm tier2 output includes `qr_redirect_chains` and risk adjustments.

## 8. Export DLP Controls
Set:
- `EXPORT_DLP_BLOCK_ON_SECRET=1`

Coverage:
- PowerBI CSV/NDJSON/ZIP exports
- Compliance evidence report
- Privacy export payload

Validation:
1. Include a test secret pattern in exportable fields.
2. Confirm output is redacted or blocked marker is applied.

## 9. CI Security Focused Job
Workflow: `.github/workflows/ci.yml` job `security-focused`.
Triggered on pull requests.
Runs:
- `tests/security/test_url_guard.py`
- `tests/security/test_model_theft_guard.py`
- `tests/security/test_cv_qr_redirect_chain.py`
- `tests/security/test_steg_detector_dct.py`
- `tests/unit/test_metrics_rbac.py`

## 10. Rollout Order
1. Redis ACL users/passwords
2. Metrics internal/auth gate
3. Internal mTLS required
4. Celery queue/signing hardening
5. Audit external anchoring
6. LLM10 thresholds and incident tuning
7. DLP strict mode
