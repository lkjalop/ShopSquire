# One-Click PowerShell Demo Bundle

Runs a real end-to-end proof with server startup, Ollama prewarm, CV readiness, incident seeding, decision trace capture, and opens the UI pages.

## Run
```powershell
& C:\AI\ShopSquire\.venv\Scripts\Activate.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo_bundle.ps1
```
Options:
- `-Api` (default `http://127.0.0.1:8081`)
- `-Python` (default `.venv/Scripts/python.exe`)

## What it does
- Starts server with `DISABLE_UI_ROUTES=0` and `CV_WARMUP_ON_START=1`.
- Prewarms Ollama via `/api/v1/chat/ollama_test` for simple and complex queries.
- Checks CV readiness via `/api/v1/admin/cv/readiness` and prints features.
- Seeds a real Email Security incident and ticket via `scripts/demo_mode.py`.
- Triggers a recommendation decision via `/api/v1/chat/query` and saves `runs/demo_decision.json`.
- Opens admin `/admin`, storefront `/ui/storefront`, and product detail `/ui/product/XPS13PLUS`.

## Proof Artifacts
- `runs/request_log.txt`: server middleware logs each HTTP request with timestamp.
- `runs/demo_proof.json`: incident and ticket snapshot (from `demo_mode.py`).
- `runs/demo_decision.json`: decision_trace_id and products from recommendation.
- DevTools Network: show live API calls and match `x-request-id` values.

## Show Decision Trace Live
- In the product detail page (`/ui/product/XPS13PLUS`), click the "Trace" button to open the Decision Trace modal.
- In the storefront, use the widget to ask a query; the widget streams `/api/v1/decisions/{id}/events/stream` live.

## Anti-skeptic checklist
- Re-run the bundle; watch new entries in `runs/request_log.txt`.
- Use `curl` to verify incidents JSON:
```powershell
curl "http://127.0.0.1:8081/api/v1/admin/email_security/incidents?limit=10&has_ticket=true"
```
- Show `x-request-id` correlation across HTTP responses, `demo_proof.json`, and DevTools Network.
- Run tests:
```powershell
C:/AI/ShopSquire/.venv/Scripts/python.exe -m pytest -q tests/security
```
