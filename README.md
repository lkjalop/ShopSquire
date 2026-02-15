# ShopSquire

ShopSquire is an autonomous, agentic AI e-commerce platform designed to be product- and vendor-agnostic.
It orchestrates specialized agent "teams" in parallel (NLP, CV/OCR, inventory, security, governance) to turn
untrusted inputs (customers, suppliers, third-party systems) into enforced decisions with an audit trail.

From a business perspective, ShopSquire aims to reduce operational cost and fraud loss while increasing
conversion by automating the highest-volume workflows (product discovery, order support, returns, supplier
communications) with guardrails and traceability.

## What It Does

- Product- and vendor-agnostic commerce API (catalog, inventory, orders, returns/support flows).
- Scenario-based agent orchestration: spawn parallel agent teams depending on the request/risk context.
- Security-first enforcement: deterministic detection tags -> playbook selection -> actions/approvals -> audit.
- Decision traceability: bitemporal decision logs + real-time trace events (SSE/WS) for drilldown and replay.
- Observability: Prometheus metrics + Grafana dashboards for ops and security lanes.

## Design Inspiration (Pragmatic, Not Magical)

- Interleaved "thinking" and routing patterns inspired by GLM-style interleaving and tool planning.
- Recursive context refresh to mitigate "context rot": decisions and evidence are persisted and pulled back
  into traces and downstream workflows rather than relying on long prompts.
- Parallel agent swarms/teams: specialized agents run concurrently, and a policy gate selects/blocks actions.

## High-Level Architecture (System)

```text
Clients (Storefront / Admin / Integrations)
            |
            v
     +-------------+         +---------------------+
     |  FastAPI    |<------->|  Redis (Agent Bus)  |
     |  Routers    |         |  Handoffs / Cache   |
     +------+------+         +----------+----------+
            |                           |
            v                           v
  +-------------------+       +---------------------+
  | Orchestrator      |       | Worker (optional)   |
  | Scenario Planner  |       | async CV / sync     |
  +----+--------+-----+       +---------------------+
       |        |
       |        +----------------------------+
       |                                     \
       v                                      v
 +-------------+  +-------------+  +------------------+
 | NLP Agents  |  | CV/OCR      |  | Inventory/ERP    |
 | Intent/RAG  |  | Forensics   |  | Sync Agents      |
 +------+------+  +------+------+  +--------+---------+
        \            /                      /
         \          /                      /
          v        v                      v
             +-------------------------------+
             | Policy Gate + Playbook Engine |
             | (enforcement + approvals)     |
             +---------------+---------------+
                             |
                             v
               +-----------------------------+
               | Postgres (OLTP + Audit)     |
               | orders/products/decision_*  |
               +-----------------------------+
                             |
                             v
               +-----------------------------+
               | Decision Trace (SSE/WS)     |
               | Evidence + Framework Maps   |
               +-----------------------------+
```

## Security Architecture (Threat Mitigation and Enforcement)

ShopSquire treats every external input as untrusted: customers, suppliers, attachments, images, and API responses.
It uses "intake-only" gates (sanitize/normalize only) followed by dedicated detection agents, correlation, and
enforced playbook-driven response.

```text
Untrusted Inputs
(web, email, images, supplier APIs)
           |
           v
 +--------------------+
 | Intake Gate        |
 | - normalize (NFKC) |
 | - strip/parse only |
 | - no actions       |
 +---------+----------+
           |
           v
 +--------------------+     +---------------------+     +----------------------+
 | Email Security     |     | CV/OCR Robustness   |     | Supply Chain Guards  |
 | - DMARC/SPF/DKIM   |     | - manipulation      |     | - baseline drift     |
 | - homoglyph scan   |     | - QR URL extraction |     | - connector hygiene  |
 | - invoice language |     | - dual OCR checks   |     | - replay controls    |
 +----------+---------+     +----------+----------+     +----------+-----------+
            \                       |                        /
             \                      |                       /
              v                     v                      v
                 +--------------------------------------+
                 | Correlation + Policy Gate            |
                 | - deterministic route/verdict        |
                 | - playbook selection                 |
                 | - contain/suspend when needed        |
                 +------------------+-------------------+
                                    |
                                    v
                 +--------------------------------------+
                 | Actions (typed, audited)             |
                 | - hold/quarantine/escalate           |
                 | - create ticket                      |
                 | - SIEM handoff (optional)            |
                 +--------------------------------------+
```

### "Prove Why It Was Flagged" (Decision Trace)

For high-signal decisions, traces include framework correlations intended for evidence and routing:

- MITRE ATT&CK technique tags (e.g. `T1566.002`)
- MITRE ATLAS tags for AI-specific threat categories (e.g. `AML.T0043`)
- DREAD breakdown + CVSS summary
- STRIDE categories
- OWASP LLM Top 10 (when applicable)
- PASTA stage marker
- SBOM posture snapshot (manifest hashes, optional `SBOM_PATH`)
- Compliance mappings (evidence/routing aid, not a certification claim): NIST CSF, ISO27001, SOC2
- Per-scenario breakdown (BEC, email-C2, CV tamper, QR injection, OCR adversarial, etc.)

## Agents (Quick Intro)

This repo contains a practical agent roster (names are conceptual, implementations live under `src/app/...`):

- Orchestrator: scenario routing, parallel agent invocation, policy-first control flow.
- Email Security Agent: BEC/phishing/ransomware patterns, auth alignment checks, ticket/playbook execution.
- CV Forensics Agent: manipulation detection, robustness signals (dual OCR, QR extraction), policy gating.
- Threat Correlation Agent: kill-chain stage + MITRE/DREAD/CVSS enrichment.
- Playbook Engine: playbook selection and typed action execution with audit linkage.
- Outbound Comms Monitor: detects email C2-like patterns (rate/entropy/periodicity) and triggers containment.
- Agent Containment: enforcement (suspend capabilities) + audit + trace events.
- Inventory Agent + Sync Worker: connectors, reorder recommendations, inventory drift and readiness.
- SIEM Adapter: normalized event handoff + reliability/DLQ endpoints (demo-friendly).

## Quick Start (Docker)

```powershell
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8080/healthz
```

Open:
- API docs: `http://127.0.0.1:8080/docs`
- Storefront (server-rendered): `http://127.0.0.1:8080/ui/`
- Grafana: `http://127.0.0.1:3005`
- Prometheus: `http://127.0.0.1:9090`

## Local Demo (Windows)

- Backend landing: http://127.0.0.1:8080/demo/links
       - Health: http://127.0.0.1:8080/health
       - Merchant dashboard: http://127.0.0.1:8080/merchant/dashboard
       - Admin React: http://127.0.0.1:3001/ (enter API key: local-owner-key)
- Buyer site: http://127.0.0.1:5173/

Setup:

1) Python venv and packages
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pyzbar pytesseract
```

2) Tesseract OCR
- Install: https://github.com/UB-Mannheim/tesseract/wiki
- Add to .env:
```powershell
Add-Content ".env" "CV_OCR_PROVIDER=tesseract"
Add-Content ".env" "TESSERACT_PATH=C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
```

3) Ollama vision model
```powershell
ollama pull llava
```
- Ensure in .env:
```powershell
Add-Content ".env" "OLLAMA_URL=http://127.0.0.1:11434"
Add-Content ".env" "CV_VISION_MODEL=llava:latest"
Add-Content ".env" "CV_VISION_ENABLED=1"
```

4) Redis (optional for agent bus/tokens)
```powershell
docker compose up -d redis
```

Run backend on 8080:
```powershell
.venv\Scripts\python.exe -m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8080 --factory
```

CV triage smoke test:
```powershell
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("dump/test-cv/macbook-QR.png"))
$payload = @{ case_id = "case-demo-qr"; images_b64 = @($b64) } | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/cv/analyze" -Headers @{"x-api-key"="local-merchant-key";"Content-Type"="application/json"} -Body $payload
```

## Demo Scripts

- Bring up stack + warmups (CV + Ollama): `scripts/start_live_demo.ps1`
- Agentic security demo (containment + trace + ops drilldown): `scripts/run_agentic_security_demo.ps1`

## Seed Demo Data (Dashboards and Backfill)

Seed baseline entities:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire"
python scripts/seed_demo_data.py
```

Seed a large order history for dashboard/backfill testing (700+ orders):

```powershell
$env:DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire"
python scripts/seed_bulk_orders.py --count 700 --uid merchant-demo --days 120
```

## Tests

Unit/integration:

```powershell
python -m pytest -q
```

Playwright UI tests exist but are opt-in on Windows (they are skipped unless explicitly enabled).
See `tests/e2e/` and `scripts/run_full_test_report.ps1`.

## Roadmap (Practical Next Steps)

From the TOGAF/SABSA and red-team gap analyses in `docs/`:

- P0: configure a real external SIEM receiver for demo evidence (`SIEM_WEBHOOK_URL` / Splunk HEC) and record delivery.
- P0: centralize RBAC/MFA for staff/suppliers and service identities; lock down admin lanes.
- P1: add correction-time truth loop (`ground_truth`, `analyst_verdict`, etc.) and surface deltas in drilldowns.
- P1: mutation-based red-team runner + trend API (>= 50 mutated payloads/run) for measurable improvement.
- P2: scale-out orchestration (multi-instance), Redis clustering, read replicas, and stronger SLO tooling.

## Documentation

Key docs referenced by the current demo plan:

- `docs/Demo_Checklist_Real_Time_Trace.md`
- `docs/Red_Team_Gap_Analysis.md`
- `docs/TOGAF_SABSA_Production_Readiness.md`

