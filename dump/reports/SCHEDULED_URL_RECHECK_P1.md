# Scheduled URL Re-check (P1) - Implementation Note

## What was implemented

- Deferred URL re-check scheduling is now persisted per incident with two stages:
  - `t15m` (15 minutes after ingest)
  - `t2h` (2 hours after ingest)
- A due-job worker cycle re-analyzes URLs and can upgrade incident routing:
  - `security_review` on high-risk/malicious delayed result
  - `human_review` on medium-risk delayed result
- Re-check outcomes are written back into incident evidence under:
  - `evidence.phishing_page_stage.scheduled_rechecks`

## Runtime components

- Scheduler service:
  - `src/app/services/url_recheck_scheduler.py`
- Email evaluate wiring:
  - `src/app/security/email_security.py`
  - schedules re-check jobs after incident persistence
- App startup/shutdown lifecycle:
  - `src/app/main.py`
  - starts/stops `url_recheck_scheduler` worker when enabled
- Admin ops endpoints:
  - `GET /api/v1/admin/email_security/url-recheck/dashboard`
  - `POST /api/v1/admin/email_security/url-recheck/run-cycle`
  - `POST /api/v1/admin/email_security/url-recheck/replay-failed`

## Env flags

- `URL_RECHECK_WORKER_ENABLED=1` to enable background worker
- `URL_RECHECK_WORKER_INTERVAL_SEC=5` to tune cycle interval

## Proof tests

- `tests/security/test_url_recheck_scheduler.py`
- `tests/email/test_admin_email_security_url_recheck.py`
