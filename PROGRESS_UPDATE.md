# ShopSquire — Progress Update

Date: 2026-01-20

Summary: this document summarizes what has been implemented so far (based on the initial PRD and security docs), what remains to be done, the current state of the recommendation engine, an ASCII architecture diagram with user flows, and a comparison to other platforms.

--

**Scope (source files referenced)**
- PRD: PRD_v2.md
- Security: SECURITY.md
- Medusa integration notes: MEDUSA_INTEGRATION.md
- Memory design: CACHE_RAG_MEMORY.md

--

**What Has Been Done (high level)**
- Project scaffold: a FastAPI application with modular routers and Pydantic models.
- Orchestrator pipeline scaffold: validate → retrieve → reason → policy → execute (stubbed provider hooks).
- Decision auditability and governance:
  - Bi-temporal decision logs concept was implemented and decision write enrichment added (retrieved_context, policy_version, approval_required, execution_status).
  - Decision lifecycle APIs: approve, reject, reopen, extend (update `src/app/routers/decisions.py`).
  - `decision_audits` table and model created for audit trail; router writes audit rows on lifecycle transitions.
- Memory & CacheRAG:
  - Redis-backed session memory endpoints and a `DummyRedis` fallback for local/test runs (`src/app/deps.py`, `src/app/services/memory.py`).
  - Session keys: `session:{uid}:summary`, `session:{uid}:kv_state`, `session:{uid}:recent_retrieval` (design matches `CACHE_RAG_MEMORY.md` ideas).
- Observability & Security:
  - Prometheus metrics: latency counters/histograms and a new `shopsquire_decision_events_total` counter (`src/app/observability/metrics.py`).
  - OpenTelemetry tracing scaffold (console exporter in dev). Security observer that computes signals and writes `security_events` best-effort (`src/app/security/observer.py`).
  - Security sanitization hardened (recursive sanitizer) in `src/app/deps.py`.
- Scoring & Governance:
  - Scoring router moved to `/api/v1/scoring` with versioning/diff/rollback endpoints.
  - Admin scoring endpoints and policy management scaffolding implemented.
- Resilience & testing:
  - Chaos flags and latency injection tests were added; flaky tests hardened by adding short DB/connect timeouts and a lazy `DummyRedis` fallback.
  - Extensive unit tests were added and stabilized; the full unit test run reports `33 passed` locally.
- Integration scaffold:
  - `docker-compose.yml` scaffolded (Postgres + Redis), `Makefile` with `test-integration` target, and a GitHub Actions workflow scaffolded for integration tests (.github/workflows/integration-tests.yml).
- Webhooks & notifications:
  - Non-blocking webhook sender utility implemented (`src/app/utils/webhook.py`). Webhooks can be configured via `config/webhooks.yml` or environment variable `DECISION_WEBHOOK_URLS`.

Key files created/changed (high-level):
- [src/app/routers/decisions.py](src/app/routers/decisions.py)
- [src/app/models/decision_audit.py](src/app/models/decision_audit.py)
- [src/app/deps.py](src/app/deps.py)
- [src/app/observability/metrics.py](src/app/observability/metrics.py)
- [src/app/utils/webhook.py](src/app/utils/webhook.py)
- [Makefile](Makefile)
- [docker-compose.yml](docker-compose.yml)
- [.github/workflows/integration-tests.yml](.github/workflows/integration-tests.yml)
- [PROGRESS_UPDATE.md](PROGRESS_UPDATE.md) (this file)

--

**What Is Left / Prioritized Roadmap**
High priority
- Finish integration harness and CI pipeline: create robust `Makefile` steps (wait for readiness, run integration tests, tear down), finalize GitHub Actions secrets for DB and external integrations.
- End-to-end integration tests: implement `tests/integration/test_e2e.py` that runs full flow (create product, create draft order, call pricing/recommend, approve decision, verify `decision_logs` persisted).
- Decision lifecycle hardening:
  - Add `decision_audits` migration to production DB and create an index/retention policy.
  - Add audit row every lifecycle change (actor, action, timestamp, metadata), and test reopen/extend flows thoroughly.
  - Add notification retries, DLQ for webhook failures, and a Prometheus counter for webhook events/errors.

Medium priority
- Notifications: integrate webhook delivery backoff/retries and an async worker for guaranteed delivery.
- External providers: flesh out third-party payment providers behind feature flags (Stripe test-mode, PayPal, Revolut, Google Pay) and incident agent connectors (Jira/Slack/Teams).
- Analytics: reintroduce optional RAG analytics (ragas) and more advanced anomaly detection (Isolation Forest) for price/time series.

Low priority / future
- Full ML model training pipelines for recommendations and online learning.
- Grafana dashboard JSON seed and automated dashboard provisioning.

--

**Recommendation Engine — Current Implementation & Status**
- Architecture & responsibilities:
  - `RecommendationService` exposes `parse_constraints()`, `retrieve_candidates()`, and `rerank_candidates()`.
  - Retrieval is implemented as a provider that returns candidate products (stubbable in tests).
  - Reranking is performed by an agent-style reranker when in cohort/rollout; a rules-based fallback is used when degradation/circuit-breaker is open or the user is not in rollout.
- Key features implemented:
  - Cohort hashing/rollout: `cohort = sha256(uid) % 100` and `rollout` percent to gate agent rerank behavior.
  - Degradation & circuit-breaker: `cb_is_open` and `cb_record` to track service health and switch to rule-based fallback.
  - Test hooks: `TEST_FORCE_BAD_SKU` to inject invalid SKUs for testing approval flows.
  - Decision logging: decisions from recommendations can be logged via `service.log_decision()` guarded by `DECISION_LOG_WRITES_ENABLED`.
  - Unit-test friendly: `retrieve_candidates` is monkeypatchable for deterministic tests.
- What remains for recommendation engine:
  - Plug an actual candidate retrieval backend (Postgres FTS or Medusa API / product catalog) — currently retrieval is a stub in tests.
  - Add ML-based scorer/reranker model (a lightweight parametric model or a small transformer embedder + ranking layer).
  - Online telemetry + bandit/AB testing controls for rollout.

--

ASCII Architecture Diagram (logical)

Client (Web/Mobile)                Admin UI
        |                              |
        v                              v
      API Gateway / FastAPI (routers)
        |---------------------------------------------------------------
        |  routers: recommend, pricing, decisions, payments, session_mem
        |  middleware: security_observer, tracing
        |---------------------------------------------------------------
                 |              |                |                |
                 v              v                v                v
        Orchestrator         Recommendations     Payments        Session Memory
        (pipeline)           (RecommendationSvc) (Provider stubs)  (Redis)
          |                      |                    |                |
  validate -> retrieve -> reason -> policy -> execute     external APIs  Redis
          |                      |                    |                |
          v                      v                    v                v
      Postgres (decision_logs, products, audits)  ->  Stripe/PayPal/etc  Redis keys

Observability: Prometheus (metrics), OpenTelemetry (traces), Logs
Security Observer: policy & signal detection -> security_events table + alerts

User flow examples
- Browse -> Recommend
  - Client -> GET /api/v1/recommend/suggest?uid=U&query=Q
  - Recommend service retrieves candidates -> reranks or rules -> proposal returned
  - If invalid SKU or safety risk -> enqueue approval and return blocked status

- Authorize Decision -> Approve/Execute
  - Admin approves via POST /api/v1/decisions/{id}/approve
  - Router writes audit, increments metric, optionally fires webhooks
  - Orchestrator executes downstream (payment, order write)

- Payment flow
  - Client creates draft order -> calls payment endpoint -> orchestrator executes provider stub -> success/failure recorded

--

Comparison with other platforms (high level)

- Shopify / Hosted SaaS:
  - Pros: extremely fast time-to-market, hosted payments, app ecosystem.
  - Cons: limited auditability and deep control over decision lifecycle, less built-in AI/observability for decision logs and governance.

- Magento / Headless Commerce + Custom ML:
  - Pros: full control, can implement custom ranking pipelines.
  - Cons: heavy ops overhead, typically no built-in decision audit trail or security observer; needs engineering to match our governance features.

- Enterprise (Salesforce Commerce Cloud, Adobe):
  - Pros: enterprise-grade scaling and integrations.
  - Cons: cost, lock-in, less experiment-friendly; customizing decision governance is complex.

Where ShopSquire differs / advantages
- Designed for decision governance: bi-temporal decision logs, `decision_audits`, approval workflows, and webhook notifications are first-class.
- Security-first: security observer, sanitization, PII/P CI detection, and auditing.
- Testable & resilient: unit tests, dummy fallbacks, chaos flags, and instrumentation (metrics + traces).
- Modular AI-friendly pipeline: orchestrator pipeline and `RecommendationService` make it easy to plug ML components or RAG memory.

Tradeoffs
- Not a drop-in hosted e-commerce product — more engineering work but much more flexible and governance-friendly.
- Requires operational setup: Postgres, Redis, monitoring, and CI to run integration tests and dashboards.

--

Actionable next steps (recommendations)
1. If you want CI to run integration tests, enable Docker on your runner and set required secrets (DB creds) in GitHub Actions. Then push the repository and let GitHub run the integration workflow.
2. Wire a webhook (set `DECISION_WEBHOOK_URLS` or edit `config/webhooks.yml`) and test using webhook.site — I can add a small test trigger endpoint if you want.
3. Complete integration tests: add `tests/integration/test_e2e.py` (I can scaffold it to exercise the core flow). Run locally via `make test-integration` once Docker is available.
4. Deploy migrations: create a database migration for `decision_audits` for production Postgres and run it during your deployment pipeline.

--

If you want, I can:
- scaffold `tests/integration/test_e2e.py` now,
- wire a webhook URL for a manual run (give me the webhook URL or say "use webhook.site"), or
- create a git branch and prepare a PR description for you to push to your remote.

--

Notes
- This summary is based on files and changes present in the workspace and the conversation history where the FastAPI MVP, decision lifecycle, memory, observability, and tests were implemented.
- Implementation choices were made for testability and resilience; production hardening (DB migrations, webhook reliability, and CI secrets) remains.
