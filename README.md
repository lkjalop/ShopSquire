## Staging Profile and Backpressure/Chaos Controls

Below are environment toggles to harden the API under load while avoiding false positives in tests. Recommended staging profile is shown first, followed by production guidance.

### Staging Profile (copy/paste)

```
# Core
DATABASE_URL=postgresql+psycopg2://shopsquire:shopsquire@localhost:5433/shopsquire_test
DISABLE_TRACING=1
SECURITY_OBSERVER_SYNC=1
SECURITY_OBSERVER_SAMPLE_RATE=0
SKIP_OBSERVER_ENDPOINTS=/health,/metrics

# Backpressure & Rate-Limits
MAX_CONCURRENCY=256
DEGRADE_ON_CONCURRENCY=1
DEGRADE_CONCURRENCY_THRESHOLD=200
RATE_LIMIT_PER_IP_PER_MIN=120
RATE_LIMIT_WINDOW_SECONDS=30

# Chaos (staging only)
CHAOS_ERROR_PROB=0.02
CHAOS_ERROR_PREFIXES=/api/v1/recommend,/api/v1/admin

# Pricing circuit breaker (feature flags in config/feature_flags.json)
# DEGRADATION.window_seconds=300
# DEGRADATION.min_requests=50
# DEGRADATION.error_rate_threshold=0.15
# DEGRADATION.open_seconds=90
```

### Production Guidance

- MAX_CONCURRENCY: 256–512 depending on CPU cores; keep `DEGRADE_ON_CONCURRENCY=1` and set threshold to ~75–85% of peak.
- RATE_LIMIT_PER_IP_PER_MIN: tune per hot path; 60–180 per minute typical for suggest endpoints; set window to 10–30s.
- CHAOS_ERROR_PROB: 0 in production; use 0.01–0.05 only in staging with `CHAOS_ERROR_PREFIXES`.
- Pricing CB: adjust `DEGRADATION` in feature flags to reflect real error budgets (min_requests, thresholds, open_seconds).

### Observability & Alerts

- Prometheus rules include:
	- 5xx error rate (`ErrorRateHigh`)
	- Rate-limit exceed spikes (`RateLimitExceededSpike`)
	- Chaos error injection detection (`ChaosErrorInjectionDetected`)
	- Concurrency saturation (`ConcurrencySaturation`)
- Grafana dashboard now has panels for HTTP rate by status, Decision Events rate, and In-flight Requests saturation.

### Silent Failure Mitigation

- Global exception handler captures unhandled errors, returns sanitized 500 JSON, and increments `shopsquire_exceptions_total{endpoint=...}`.
- Backpressure middleware records `shopsquire_inflight_requests{service="api"}` for saturation; rate-limit and chaos errors increment dedicated counters.
- Security observer logs high/critical events; escalation endpoint writes incidents and can dispatch webhooks.
- Decision logging persists proposals and policy metadata; optional RAGAS evaluation can be enabled via `RAGAS_EVAL_ENABLED` in feature flags to score outputs and flag anomalies.

### Advanced Stores (TimescaleDB, Graph)

- TimescaleDB: convert `decision_logs` and `security_events` to hypertables for fast time-window queries and retention policies; use continuous aggregates for latency/error SLOs.
- Context Graph: model `users`, `orders`, `decisions`, `events` as nodes; edges like `user->decision (initiated)`, `decision->incident (related)` enable root-cause tracing; secure with role-based access and field-level redaction.
- Security & Privacy: validate inputs (OWASP LLM Top 10), redact PII in logs, enforce per-tenant scoping; run differential privacy sampling for analytics when possible.

### Try It Locally

```
# Disable backpressure for test suites
$env:DATABASE_URL = "sqlite:///test.sqlite"
$env:DISABLE_TRACING = "1"
$env:SECURITY_OBSERVER_SYNC = "1"
$env:SECURITY_OBSERVER_SAMPLE_RATE = "0"
$env:RATE_LIMIT_PER_IP_PER_MIN = "0"
$env:MAX_CONCURRENCY = "0"
$env:CHAOS_ERROR_PROB = "0"
$env:SKIP_OBSERVER_ENDPOINTS = "/api/v1/recommend,/api/v1/admin"
& ".venv/Scripts/python.exe" -m pytest -q tests/chaos tests/load
```

# ShopSquire API (MVP Scaffold)

Agentic commerce service scaffold implementing the core patterns from PRD v2 and SECURITY:
- FastAPI service with DI providers
- Orchestrator (validate → retrieve → reason → policy → execute/escalate)
- Transaction Firewall (caps, thresholds, idempotency, circuit breakers)
- Security Observer (lite): unicode normalize, PII mask, jailbreak regex, severity bands
- Redis CacheRAG memory (summary, kv_state, recent_retrieval)
- PostgreSQL schema (customers, products, inventory, draft_orders, orders, decision_logs)
- Governance: feature flags, rollout percentage, kill switches
- Medusa webhooks & payments (Stripe test stub)

## Quick Start (Docker)

```bash
cp .env.example .env
# Optionally edit DATABASE_URL/REDIS_URL in .env
docker compose up -d db redis
# Apply DB migrations (Alembic is the source of truth)
poetry run alembic -c alembic.ini upgrade head
# Build & run API (requires Dockerfile if building container) or run locally:
```

## Quick Start (Local Python)

```bash
# Python 3.10+
pip install pipx
pipx install poetry
poetry install
cp .env.example .env
# Start API
poetry run uvicorn src.app.main:app --host 0.0.0.0 --port 8080
```

OpenAPI docs: http://localhost:8080/docs

## Run Tests

```bash
poetry run pytest -q
```

## Database Setup (Detailed)

See `docs/DB_SETUP.md:1` for the exact local flow (Postgres + Alembic) and the optional TimescaleDB override.

## Project Layout

- src/app/main.py — FastAPI app, routers, middleware
- src/app/services/* — orchestrator, memory, payments
- src/app/security/* — observer middleware, firewall
- src/app/routers/* — domain routers and admin/flags
- src/app/models/* — SQLAlchemy session and Pydantic schemas
- config/feature_flags.json — flags + rollout
- config/security/taxonomy/* — risk scoring taxonomy stubs
- db/schema.sql — PostgreSQL schema
- db/seed.sql — Minimal seed data

## Notes
- This scaffold is MVP-friendly. Replace stubs and TODOs as you integrate real logic and Medusa/Stripe accounts.
- The default settings assume local Postgres and Redis.
