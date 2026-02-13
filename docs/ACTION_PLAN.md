# Action Plan (Owners & Timelines)

Timeboxes are rough guidance for demo readiness; adjust per team capacity.

## Core Showcase
- Feature Prioritization — Owner: Product Lead — 1 day
  - Finalize which flows to demo: Complaints intake → CV evidence → Fraud enrichment → Warehouse verification → Decision logs → Notifications.
- Demo Script — Owner: Product + Eng — 1-2 days
  - Narrative, step-by-step commands, expected outputs (include decision-log inspection).

## Integrations & Enhancements
- CV Provider + Trust + Fraud — Owner: Backend — 2-3 days
  - Trust routing thresholds & policy configs; optional Google/Azure CV provider wiring; graceful fallbacks.
- Notifications Senders — Owner: Backend — 2-3 days
  - Integrate SES/SendGrid/Twilio; capture decision logs prior to dispatch; add minimal provider config & tests.
- Receipt OCR vs Order — Owner: Backend — 2 days
  - OCR extraction (Tesseract or provider OCR); compare with `orders.serial_number`/`order_serials`; manual override path; tests.
- Product Embeddings — Owner: ML/Infra — 3-5 days
  - Basic embeddings (e.g., sentence-transformers); similarity scoring for recommendations & catalog checks; cache index; tests.
- Reverse Image Search — Owner: ML/Infra — 3-4 days
  - phash index + search; flag known duplicates; mismatch signals exposed to fraud scorer & warehouse verification; tests.
- Observability & Alerts — Owner: Ops — 2-3 days
  - Quiet tracing in tests (`DISABLE_TRACING=1`); Prometheus counters + Alertmanager rules; span verification for complaint pipeline.
- Postgres Migrations — Owner: Backend — 2 days
  - Generate migrations for `decision_logs`, `cv_analyses`, `fraud_image_hashes`, `cases`, `return_labels`, `orders`; validate local + staging.
- CV Provider Creds & Docs — Owner: Docs — 1 day
  - Document provider options, env flags, local demo steps, and test skip behavior.

## Validation & QA
- Model Presence Matrix — Owner: QA — 1 day
  - Expand text/vision model presence tests; ensure graceful skip when unavailable; add budget usage test coverage (done for orchestrator).
- E2E Stability — Owner: QA — 1-2 days
  - Run repeated E2E flows under fault injection; capture flaky points; feed fixes back to owners.

## Deliverables
- Demo guide: `docs/DEMO_SHOWCASE_FLOW.md` (created)
- Integration docs: `docs/CV_PROVIDER_SETUP.md` (to be created)
- Action plan (this doc)
- Test coverage: presence, rerank, decision logs, pipeline E2E
- Migrations: scripts + README
