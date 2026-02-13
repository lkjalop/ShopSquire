# Demo Mode: Real, Reproducible Proof

This guide runs a live end-to-end flow: backend emits a real incident via the public API, the admin UI shows it with playbook tags, and tickets link for human escalation. It also leaves verifiable artifacts.

## Prereqs
- Windows (PowerShell) or any OS with Python 3.10+
- Virtual env activated and dependencies installed
- Backend reachable at `http://127.0.0.1:8081` with `DISABLE_UI_ROUTES=0`

## Start API (one-time)
```powershell
& C:\AI\ShopSquire\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "sqlite+pysqlite:///C:/AI/ShopSquire/tmp/e2e.sqlite"
$env:DISABLE_UI_ROUTES = "0"
$env:API_PORT = "8081"
$env:BACKPRESSURE_TEST_DELAY_SEC = "0.2"
C:/AI/ShopSquire/.venv/Scripts/python.exe -m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8081 --factory
```

## Run Demo Script
```powershell
C:/AI/ShopSquire/.venv/Scripts/python.exe scripts/demo_mode.py --api http://127.0.0.1:8081 --open-ui
```
Optional autostart:
```powershell
C:/AI/ShopSquire/.venv/Scripts/python.exe scripts/demo_mode.py --api http://127.0.0.1:8081 --autostart --open-ui
```

## What You’ll See
- POST `/api/v1/email_security/evaluate` returns a verdict: severity, tags, playbook.
- GET `/api/v1/admin/email_security/incidents?has_ticket=true` returns the incident with `ticket_id` and a playbook badge.
- Admin UI opens at `/admin`; navigate to Security → Inline Email Incidents and the dedicated Email Incidents page.
- Toggle "Only Important" (warning+error) and click the ticket deep link.

## Proof Artifacts
- Server appends to `runs/request_log.txt` for every HTTP request (middleware). Show this live.
- Script writes `runs/demo_proof.json` with request IDs, verdict, and incidents snapshot.
- Export CSV from Email Incidents page to capture the incident row.
- Use `curl` to confirm:
```powershell
curl "http://127.0.0.1:8081/api/v1/admin/email_security/incidents?limit=10&has_ticket=true"
```

## Anti-Skeptic Playbook
- "Fake video?" Show DevTools Network calls in real time and match them with the `runs/request_log.txt` timestamps.
- "No autonomy?" Re-run `demo_mode.py`; the system auto-creates incidents + tickets from deterministic rules without manual steps.
- "Unsafe?" Open feature flags, show redaction in evidence, and use the ticket deep link for human escalation.
- "Not reproducible?" Provide the exact commands above; re-run on a clean SQLite DB (`tmp/e2e.sqlite`).

## Reset / Cleanup
- Delete or clear `tmp/e2e.sqlite` to reset local DB state.
- Remove `runs/demo_proof.json` if you want a fresh proof file.

## Bonus: Test Suite
Run deterministic security tests:
```powershell
C:/AI/ShopSquire/.venv/Scripts/python.exe -m pytest -q tests/security
```
