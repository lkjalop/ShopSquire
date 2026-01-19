# Changelog

## 2026-01-20
- Fix: Improve test resilience when Redis/Postgres are unavailable in local/test environments.
  - Use lazy Redis client creation with quick `ping()` health check and `DummyRedis` fallback to avoid blocking calls.
  - Add short Postgres `connect_timeout` (1s) in SQLAlchemy engine configuration to fail fast on DB connect.
  - Add optional internal `timings` instrumentation for the orchestrator (hidden behind `SHOW_INTERNAL_TIMINGS` env var).
  - Removed temporary debug helper used during troubleshooting.

These changes reduce intermittent test flakiness caused by unavailable external services. The default behavior remains unchanged in environments where Redis and Postgres are available.
