Title: Add integration test scaffold, webhook test script, and decision-audit progress update

Summary:
- Adds integration test scaffold `tests/integration/test_e2e.py` (skipped by default unless `RUN_INTEGRATION=1`).
- Adds `scripts/send_test_webhook.py` to send a sample decision event to configured webhooks.
- Updates `config/webhooks.yml` with an example commented entry and supports `DECISION_WEBHOOK_URLS` environment variable.
- Adds GitHub Actions workflow `.github/workflows/integration-tests.yml` to run integration tests on CI (requires Docker and secrets to be configured).
- Adds `PROGRESS_UPDATE.md` summarizing implementation status and next steps.

Notes for reviewers:
- Integration tests require Docker and the Postgres/Redis stack; the CI workflow is scaffolded but needs secrets and possibly image tags depending on your infra.
- The webhook script is intentionally best-effort and non-blocking; it uses simple HTTP POST and small timeouts.
- All unit tests pass locally (`pytest` shows 33 passed).

How to run locally:
- Unit tests:
  .venv/Scripts/python.exe -m pytest -q
- Integration tests (requires Docker Desktop):
  make test-integration
- Manual webhook test (configure webhook in config/webhooks.yml or set DECISION_WEBHOOK_URLS):
  python scripts/send_test_webhook.py

*** End of PR description
