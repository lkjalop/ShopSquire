### 2026-01-23

- Recommend and Pricing: Added X-Rate-Limit-* headers to expose reason, tokens remaining, and cost remaining for each request. This improves client visibility and supports deterministic testing.
- Security Tests: Added tests/security/test_rate_limits.py header presence test and marked env-dependent budget exceed case as xfail when server is not restarted.
- Pricing Tests: Added tests/security/test_pricing_rate_limits.py to validate consistent headers on pricing.
- Auth: Continued migration toward hashed session tokens only.
# Changelog

## 2026-01-20
- Fix: Improve test resilience when Redis/Postgres are unavailable in local/test environments.
  - Use lazy Redis client creation with quick `ping()` health check and `DummyRedis` fallback to avoid blocking calls.
  - Add short Postgres `connect_timeout` (1s) in SQLAlchemy engine configuration to fail fast on DB connect.
  - Add optional internal `timings` instrumentation for the orchestrator (hidden behind `SHOW_INTERNAL_TIMINGS` env var).
  - Removed temporary debug helper used during troubleshooting.

These changes reduce intermittent test flakiness caused by unavailable external services. The default behavior remains unchanged in environments where Redis and Postgres are available.
