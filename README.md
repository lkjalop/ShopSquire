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