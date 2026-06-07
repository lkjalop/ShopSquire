# ShopSquire

> AI intelligence layer + shift-left security for autonomous e-commerce operations.
> Not a Shopify replacement — a policy-bounded orchestration and enforcement layer
> designed to sit on top of existing commerce stacks.

---

## What It Is

ShopSquire implements the full agent stack required for zero-employee commerce operations:
multi-agent recommendation pipeline, in-pipeline security enforcement, bitemporal decision
audit trail, and autonomous exception handling. The owner dashboard is governance-only —
it is never in the runtime path.

It is a **synthesis artifact**, not a green-field invention. The architecture was built against
a formal autonomous e-commerce specification, the AI/retrieval layer against a structured RAG
engineering curriculum, the compliance layer against GRC training frameworks, and the security
depth from security architecture principles, practitioner sessions, and applied offensive research
into attacker evasion techniques. Each source contributed a distinct layer; the codebase is the
proof that those layers were synthesised into one coherent system.

The 13,904-line `recommend.py` is what iterative, prompt-assisted development against a formal
specification produces before the R5 refactor. The finalizer pattern and scatter-gather scaffold
already present in the codebase show where that extraction is heading.

---

## Platform Architecture

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║              SHOPSQUIRE — AUTONOMOUS COMMERCE INTELLIGENCE                           ║
║   AI Orchestration + Shift-Left Security for Zero-Employee E-Commerce Operations     ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

┌──────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — CUSTOMER & MERCHANT INTERFACES                                            │
│                                                                                      │
│  ┌──────────────────────────┐  ┌────────────────────────┐  ┌──────────────────────┐ │
│  │  React/TypeScript SPA    │  │  Decision Trace UI     │  │  Email Security Lab  │ │
│  │  (Vite :5173)            │  │  WebSocket + SSE       │  │  (Merchant :8080)    │ │
│  │  Product chat + vision   │  │  Bitemporal agent      │  │  BIMI / BEC /        │ │
│  │  Image upload / QR scan  │  │  chain drilldown       │  │  SPF/DMARC analysis  │ │
│  └─────────────┬────────────┘  └───────────┬────────────┘  └──────────┬───────────┘ │
└────────────────┼──────────────────────────┼──────────────────────────┼─────────────┘
                 └──────────────┬───────────┘                           │
                                ▼                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 2 — API GATEWAY  (FastAPI :8080, 103 routers)                                 │
│                                                                                      │
│  JA3/JA4 TLS Fingerprint Middleware → Rate Limiting → JWT Auth → CORS               │
│  AUDIT_CHAIN_SECRET validated at startup  |  _block_response() → HTTP 403 default   │
│  Prometheus metrics middleware  |  Request audit logging on every sensitive route    │
└────────────────────────────────────┬─────────────────────────────────────────────────┘
                                     │
         ┌───────────────────────────┼──────────────────────────┐
         ▼                           ▼                           ▼
┌─────────────────────┐  ┌───────────────────────────┐  ┌────────────────────────────┐
│  RECOMMEND ROUTER   │  │  SECURITY ENGINE           │  │  MERCHANT DASHBOARD        │
│                     │  │                            │  │                            │
│  4-phase orchestr.: │  │  Email security (~5k loc)  │  │  Governance surface only   │
│  EXPLORE            │  │  CISA KEV local catalog    │  │  Exception visibility      │
│  EVALUATE           │  │  LOLBin catalog (17 entries│  │  Decision log access       │
│  PLAN               │  │  + ATT&CK IDs)             │  │  Security telemetry        │
│  ACTION             │  │  Sandbox detonation queue  │  │  Business performance      │
│                     │  │  Fraud scorer (26 signals) │  │  Owner policy review       │
│  recommend_pipeline │  │  Policy gate agent         │  │  Never a runtime dep.      │
│  v2 scatter-gather  │  │  Supplier domain guard     │  │                            │
└──────────┬──────────┘  └─────────────┬─────────────┘  └────────────────────────────┘
           │                           │
           └──────────────┬────────────┘
                          ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — INTELLIGENCE LAYER  (15+ coordinated agents)                              │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  COMPLEXITY SCORER  (10 signals → 0-10 scale) → 3-TIER MODEL ROUTING         │   │
│  │                                                                               │   │
│  │  0-3  →  llama3.3:8b   (fast path, FAQ/simple queries)                       │   │
│  │  4-6  →  mixtral:8x7b  (mid-tier, multi-constraint queries)                  │   │
│  │  7-10 →  qwen3:14b     (large, with thinking mode for complex reasoning)     │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  RECOMMENDATION AGENTS:                                                              │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌───────────────────────┐ │
│  │ NLP_Search     │ │ Candidate      │ │ Product        │ │ NQE                   │ │
│  │ Agent          │ │ Retrieval      │ │ Ranking        │ │ (Next Question Engine)│ │
│  │ Intent extract │ │ Agent (RRF)    │ │ Agent          │ │ Stock-aware, context- │ │
│  │ + constraint   │ │ async parallel │ │ KB exclusions  │ │ persistent, embedding │ │
│  │ parsing        │ │ gather         │ │ + MMR diversity│ │ ranked question pool  │ │
│  └────────────────┘ └────────────────┘ └────────────────┘ └───────────────────────┘ │
│                                                                                      │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌───────────────────────┐ │
│  │ Inventory      │ │ Upsell         │ │ Playbook       │ │ Policy_Gate           │ │
│  │ Agent          │ │ Engine         │ │ Engine         │ │ Agent                 │ │
│  │ OOS guard      │ │ co-purchase    │ │ deterministic  │ │ action authorization  │ │
│  │ rank penalty   │ │ affinity +     │ │ playbook       │ │ before execution      │ │
│  │ stock check    │ │ use-case NLP   │ │ selection      │ │                       │ │
│  └────────────────┘ └────────────────┘ └────────────────┘ └───────────────────────┘ │
│                                                                                      │
│  SECURITY AGENTS:                                                                    │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌───────────────────────┐ │
│  │ Security       │ │ CV_Label       │ │ Fraud_Scoring  │ │ GAN / Adversarial     │ │
│  │ Observer Agent │ │ Agent          │ │ Agent          │ │ Image Detector        │ │
│  │ MAESTRO CSA    │ │ Vision LLM     │ │ 26 signals     │ │                       │ │
│  │ MITRE ATLAS    │ │ OCR (tesseract)│ │ JA3/JA4/GeoIP  │ │ Off-topic image gate  │ │
│  │ event mapping  │ │ QR decode      │ │ ASN risk       │ │ before retrieval      │ │
│  │                │ │ Steg LSB detect│ │ velocity/device│ │                       │ │
│  └────────────────┘ └────────────────┘ └────────────────┘ └───────────────────────┘ │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  MULTI-ARM BANDIT — Recommendation Arm Selection                              │   │
│  │  balanced | explore_novelty | price_value | personalized_heavy                │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────┬──────────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — RETRIEVAL & MEMORY LAYER                                                  │
│                                                                                      │
│  RRF SCATTER-GATHER (async parallel merge):                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐  │
│  │ SQL DB   │ │ Vector   │ │ Fraud    │ │ CV Score │ │ Inventory Filter         │  │
│  │ search   │ │ search   │ │ signal   │ │ inject   │ │ OOS=-0.5 / unknown=-0.1  │  │
│  │          │ │ pgvector │ │ inject   │ │          │ │ re-sort before assembly  │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────────────────┘  │
│                                                                                      │
│  ┌────────────────────────────────┐  ┌────────────────────────────────────────────┐ │
│  │ SEMANTIC CACHE                 │  │ REDIS SESSION MEMORY                       │ │
│  │ pgvector cosine similarity     │  │ session:{uid}:summary                      │ │
│  │ 4h TTL, cache-hit fast path    │  │ session:{uid}:kv_state                     │ │
│  │ skips LLM + retrieval entirely │  │ session:{uid}:recent_retrieval             │ │
│  └────────────────────────────────┘  │ session:{uid}:agent_steps                  │ │
│                                      └────────────────────────────────────────────┘ │
│  ┌────────────────────────────────┐                                                  │
│  │ USE-CASE KNOWLEDGE BASE        │  7 use cases: gaming, university, engineering,  │
│  │ config/use_case_kb.json        │  creative, corporate, calls, ai_ml              │
│  │ required specs + exclusions    │  NQE guidance per use case                      │
│  └────────────────────────────────┘                                                  │
└───────────────────────────────────────┬──────────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 5 — CONTROL PLANE & AUDIT                                                     │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  recommend_response_finalizer                                                 │   │
│  │  INVARIANT: LLM narrative ≡ JSON payload ≡ decision trace                    │   │
│  │  Prevents cross-product spec hallucination (e.g. "240Hz" on wrong product)   │   │
│  │  All three must agree before response exits the pipeline                     │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  decision_log (bitemporal)   |  exception_queue   |  policy_evaluation_log          │
│  WORM audit trail            |  dual-control supplier changes                        │
│  confidence thresholds       |  prohibited actions list  |  rollback logic           │
│  atomic voucher (Redis SETNX)|  inventory injection guard                            │
└───────────────────────────────────────┬──────────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 6 — INFRASTRUCTURE  (Docker Compose — 7 services)                             │
│                                                                                      │
│  ┌─────────┐ ┌─────────────────────┐ ┌───────┐ ┌─────────────┐ ┌────────────────┐  │
│  │   api   │ │  db                 │ │ redis │ │ sync-worker │ │ celery-worker  │  │
│  │  :8080  │ │  PostgreSQL         │ │ :6379 │ │             │ │                │  │
│  │         │ │  + pgvector         │ │       │ │             │ │ sandbox queue  │  │
│  └─────────┘ └─────────────────────┘ └───────┘ └─────────────┘ └────────────────┘  │
│                                                                                      │
│  ┌──────────────────────────┐  ┌─────────────────────────────────────────────────┐  │
│  │  crowdstrike-poll        │  │  syslog-listener                                │  │
│  └──────────────────────────┘  └─────────────────────────────────────────────────┘  │
│                                                                                      │
│  Neo4j: optional  --profile neo4j  →  GNN fraud ring detection (networkx fallback)  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Security Flow — Untrusted Input Pipeline

```
Untrusted Inputs (customer chat, uploaded images, supplier emails, API responses)
        │
        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│  INTAKE GATE                                                                  │
│  normalize (NFKC) → strip → parse only → no actions taken here               │
└────────┬──────────────────────────────────────────────────────────────────────┘
         │
         ├────────────────────────┬──────────────────────────┐
         ▼                        ▼                           ▼
┌──────────────────┐   ┌─────────────────────┐   ┌──────────────────────────┐
│  EMAIL SECURITY  │   │  CV / IMAGE TRIAGE  │   │  SUPPLIER GUARD          │
│  BEC detection   │   │  Vision LLM (llava) │   │  Domain validation       │
│  BIMI verify     │   │  OCR extraction     │   │  Trusted domain table    │
│  SPF/DKIM/DMARC  │   │  QR decode + URL    │   │  BEC pattern match       │
│  homoglyph scan  │   │  Steg LSB detect    │   │  Financial request flag  │
│  invoice lang.   │   │  GAN/adversarial    │   │                          │
│  BIMI trust score│   │  Off-topic gate     │   │                          │
└────────┬─────────┘   └──────────┬──────────┘   └─────────────┬────────────┘
         └────────────────────────┼──────────────────────────────┘
                                  ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│  CORRELATION + POLICY GATE                                                    │
│  deterministic verdict  |  playbook selection  |  MAESTRO boundary check     │
│  MITRE ATLAS event map  |  CISA KEV auto-escalate regardless of CVSS         │
│  LOLBin behavioral match (17 entries, T-codes)  |  confidence threshold gate │
└──────────────────────────────────┬────────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                           ▼
┌──────────────┐         ┌─────────────────┐         ┌───────────────────────┐
│  ALLOW       │         │  BLOCK / 403    │         │  QUARANTINE / ESCALATE│
│  inject safe │         │  fail-closed    │         │  sandbox detonation   │
│  hints into  │         │  default        │         │  queue (Celery)       │
│  LLM preamble│         │                 │         │  incident ticket      │
│  [SECURITY]  │         │                 │         │  SIEM handoff         │
│  prefix if   │         │                 │         │                       │
│  steg/QR/adv │         │                 │         │                       │
└──────────────┘         └─────────────────┘         └───────────────────────┘
         │                         │                           │
         └─────────────────────────┼───────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│  DECISION LOG (bitemporal)                                                    │
│  module | policy applied | input context | affected objects | timestamp       │
│  outcome | confidence score | ATLAS event | ATT&CK technique | DREAD score   │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## What Makes It Different

### 1. The combination is uncommon
Most AI engineers have not implemented MAESTRO (CSA Feb 2025 agentic AI framework). Most
security engineers cannot build a multi-agent retrieval pipeline with RRF scatter-gather,
semantic caching, and complexity-based model routing. ShopSquire demonstrates both in one
coherent system — not as separate projects.

### 2. `recommend_response_finalizer` — correctness invariant
The finalizer enforces that the LLM narrative text, the JSON product payload, and the decision
trace all describe the same products in the same order before any response exits the pipeline.
Most AI systems ship without this. The visible failure mode: "240Hz" appearing in the
explanation for a product whose spec says "144Hz" because the LLM referenced a different
candidate from the retrieval set. The finalizer makes this class of error impossible.

### 3. Bitemporal audit trail on every recommendation
Every agent step, security event, policy gate decision, and LLM interaction is logged with
trace IDs. The decision trace UI shows exactly why a product was recommended or blocked:
which agent fired, what signal triggered it, what confidence score was applied, what policy
was evaluated, and what ATLAS/ATT&CK/DREAD tags apply. This is observable from outside the
system — not just in code comments.

### 4. In-pipeline security, not post-hoc audit
Security agents run inside the recommendation orchestrator, intercepting and transforming
requests before retrieval begins. The off-topic image gate rejects adversarial images before
they reach the vector store. The QR-decoded URL is injected into the LLM preamble when a
payload URL is found in an uploaded image. The `[SECURITY]` prefix is injected into the
assistant response when steganography, QR injection, or adversarial detection fires.

### 5. CV return fraud triage
Vision LLM (llava via Ollama) + Tesseract OCR + QR decode (pyzbar) + steganography LSB
extraction (PIL) + adversarial image detection in one pipeline, wired to the recommendation
and incident routing flows. Rare in commerce AI systems.

### 6. Fail-closed defaults throughout
Not bolted on:
- `_block_response()` defaults to HTTP 403 (not 200)
- `AUDIT_CHAIN_SECRET` validated eagerly at startup (fails closed in prod)
- Inventory injection guard prevents OOS products entering recommendations
- Atomic voucher endpoint uses Redis SETNX lock + DB transaction
- Cart stock gate checks inventory before add-to-cart

---

## Technical Inventory

### Codebase Scale
| Component | Count |
|-----------|-------|
| Routers (FastAPI) | 103 |
| Services | 203 |
| Security modules | 128 |
| `recommend.py` lines | 13,904 |
| Docker Compose services | 7 |
| LOLBin catalog entries (+ ATT&CK IDs) | 17 |
| CISA KEV catalog entries (local) | 7 |
| Use-case knowledge base entries | 7 |
| Fraud scoring signals | 26 |

### Agent Roster
| Agent | Role |
|-------|------|
| NLP_Search_Agent | Intent extraction, constraint parsing |
| Candidate_Retrieval_Agent | RRF async scatter-gather across 5 sources |
| Product_Ranking_Agent | KB exclusions, MMR diversity, spec scoring |
| NQE (Next Question Engine) | Stock-aware, context-persistent disambiguation |
| Inventory_Agent | OOS guard, rank penalty, stock check |
| Upsell_Engine | Co-purchase affinity + use-case cross-sell |
| Fraud_Scoring_Agent | 26 signals, JA3/JA4, GeoIP/ASN, velocity |
| Security_Observer_Agent | MAESTRO/ATLAS event mapping, threat correlation |
| CV_Label_Agent | Vision LLM, OCR, QR decode, steg LSB, adversarial |
| GAN/Adversarial_Image_Detector | Off-topic gate before retrieval |
| Policy_Gate_Agent | Action authorization before execution |
| Playbook_Engine | Deterministic playbook selection + typed actions |
| Product_Identity_Agent | Spec extraction from product images |
| Email_Security_Engine | BEC, BIMI, SPF/DMARC, homoglyph, invoice language |
| Supplier_Domain_Guard | Trusted domain table, BEC financial request flag |

### Security Frameworks Implemented
| Framework | Coverage |
|-----------|----------|
| MAESTRO (CSA Feb 2025) | Agentic AI boundary enforcement on every agent call |
| MITRE ATLAS (Oct 2025) | Context poisoning, memory manipulation, RAG credential harvesting |
| MITRE ATT&CK | LOLBin T-codes, technique tags in decision log |
| OWASP LLM Top 10 2025 | LLM08 vector/embedding weaknesses → semantic_cache.py |
| OWASP Agentic AI Top 10 (Dec 2025) | Mapped in security modules |
| JA4 TLS fingerprinting | TLS fingerprint middleware, fraud scorer signal |
| CISA KEV | Local catalog + live feed option, auto-escalate on hit |

### Compliance Coverage
| Framework | Status |
|-----------|--------|
| PCI DSS | Control matrix in `docs/COMPLIANCE-FRAMEWORK-CONTROL-MATRIX.md` |
| ISO 27001 | Control coverage mapped with ✅/⚠️/❌ per control |
| ISO 42001 (AI management) | Mapped |
| GDPR | Data handling controls, retention/deletion policies |
| EU AI Act | Risk classification mapped |
| NIST AI RMF | Coverage mapped |
| APP (Australian Privacy Principles) | Mapped — ANZ deployment target |

### Infrastructure
```
Service             Port    Role
─────────────────── ─────── ─────────────────────────────────────────
api                 8080    FastAPI backend, all routers
db                  5432    PostgreSQL + pgvector extension
redis               6379    Session memory, semantic cache, task queue
sync-worker         —       Inventory sync, ERP connectors
celery-worker       —       Async tasks, sandbox detonation queue
crowdstrike-poll    —       EDR signal ingestion
syslog-listener     —       Syslog event ingestion
neo4j (optional)    7474    GNN fraud ring detection (--profile neo4j)
```

---

## Design Foundation (Honest)

ShopSquire was built as a deliberate synthesis from multiple learning sources, each contributing
a distinct architectural layer:

| Source | What it contributed |
|--------|---------------------|
| Formal autonomous e-commerce architecture specs (design reference) | Module structure, zero-employee doctrine, exception model, audit requirements, governance boundary |
| Zero to Mastery — RAG for LLMs | Semantic cache, pgvector retrieval, RRF patterns, embedding pipeline, LLM orchestration |
| GRC Mastery (Abed Hamdan / UnixGuy) | PCI DSS / ISO 27001 / ISO 42001 compliance layer, control matrix, audit trail requirements |
| Go Cloud Careers — Security Architecture | Vendor-agnostic controls, least-privilege IAM, secrets management, cloud-agnostic pattern design |
| Cyberstash (ANZ cybersecurity) — CEO sessions | Real attack patterns, threat intelligence grounding for specific detection signals |
| Janusec (open-source WAF) | WAF/request inspection logic patterns |
| YouTube — threat modeling frameworks | MAESTRO, MITRE ATLAS, OWASP LLM Top 10 framing |
| YouTube — hacker evasion techniques | JA3/JA4 fingerprinting, LOLBin detection, steganography LSB, adversarial image gates |

The security depth is defensive design informed by offensive research — not a compliance
checklist. The JA3/JA4 fingerprinting exists because TLS client fingerprinting is how you
catch tools that rotate IPs. The steganography detector exists because LSB payload injection
in product images is a demonstrated attack vector. The LOLBin catalog exists because Windows
living-off-the-land binaries are the evasion path of choice for post-exploitation activity.

---

## Quick Start (Docker)

```powershell
cp .env.example .env
# Edit .env — set OWNER_API_KEY, DATABASE_URL, REDIS_URL
docker compose up -d --build
curl http://127.0.0.1:8080/healthz
```

| Interface | URL |
|-----------|-----|
| API docs (Swagger) | http://127.0.0.1:8080/docs |
| Storefront (buyer) | http://127.0.0.1:5173/ |
| Merchant dashboard | http://127.0.0.1:8080/merchant/dashboard |
| Email security lab | http://127.0.0.1:8080/merchant/email-lab |
| Decision trace | http://127.0.0.1:8080/decisions/{id}/events/ws |
| Demo links index | http://127.0.0.1:8080/demo/links |

## Local Development (Windows)

```powershell
# 1. Python environment
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pyzbar pytesseract

# 2. Tesseract OCR (for CV triage)
# Install from https://github.com/UB-Mannheim/tesseract/wiki
Add-Content ".env" "CV_OCR_PROVIDER=tesseract"
Add-Content ".env" "TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe"

# 3. Ollama vision model (for CV + recommendation LLM)
ollama pull llava
ollama pull llama3.3
Add-Content ".env" "OLLAMA_URL=http://127.0.0.1:11434"
Add-Content ".env" "CV_VISION_MODEL=llava:latest"
Add-Content ".env" "CV_VISION_ENABLED=1"

# 4. Database
docker compose up -d db redis
$env:DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire"
.venv\Scripts\python.exe -m alembic upgrade head

# 5. Seed demo data
python scripts/seed_demo_data.py          # products, users, baseline
python scripts/seed_bulk_orders.py --count 700 --uid merchant-demo --days 120

# 6. Run backend
.venv\Scripts\python.exe -m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8080 --factory

# 7. Run frontend (separate terminal)
cd src/frontend/storefront-react && npm install && npm run dev
```

### CV Triage Smoke Test
```powershell
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("dump/test-cv/macbook-QR.png"))
$payload = @{ case_id = "case-demo-qr"; images_b64 = @($b64) } | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/cv/analyze" `
  -Headers @{"x-api-key"="local-merchant-key";"Content-Type"="application/json"} `
  -Body $payload
```

---

## Tests

```powershell
# Full suite
python -m pytest -q

# Key contract tests (finalizer invariant, feature flags, inventory thresholds)
python -m pytest tests/test_recommend_finalizer.py tests/test_flags.py `
  tests/test_inventory_thresholds.py tests/test_support_thresholds_config.py -q

# Playwright E2E (opt-in on Windows)
# See tests/e2e/ and scripts/run_full_test_report.ps1
```

Contract tests enforce the finalizer invariant: any response where the LLM narrative
describes products not present in the JSON payload fails at the test boundary, not in
production.

---

## Demo Order (Recommended)

Do **not** lead with the shopping flow on first impression — Ollama response time on a local
GPU-less machine is 5–15s. Lead with what has no LLM in the critical path:

1. **Email lab** — paste a supplier BEC email ("please update our bank account to BSB...").
   DKIM failed + domain 3 days old + financial request pattern + BIMI mismatch → result in
   under 2 seconds. No LLM.

2. **CV return fraud** — upload a damaged laptop photo. Vision identifies device, OCR extracts
   text, QR decoded to suspicious URL, steg detector finds LSB payload. Decision trace shows
   every agent step, every signal, ATLAS event mapping.

3. **Decision audit trail** — pull any trace. Show bitemporal reasoning, agent chain, policy
   gate evaluation, fraud score breakdown with signal-level detail.

4. **Product recommendation** — with upfront acknowledgement: "I'm running local Ollama to
   avoid API costs. The architecture is provider-agnostic via `llm_provider.py` — swapping to
   Claude API or GPT-4o mini drops this to 1–2s."

---

## Known Limitations (Honest)

| Limitation | Context |
|------------|---------|
| `recommend.py` is 13,904 lines | Grew through iterative prompt-assisted development against a spec. Sprint R5 extraction planned. The finalizer pattern and scatter-gather scaffold show the direction. |
| Ollama latency (5–15s) on CPU-only | Architecture is provider-agnostic. `llm_provider.py` supports OpenAI/Anthropic. Running local to avoid API costs. |
| Seeded catalog only (~80–85 laptop products) | Real catalog integration requires a commerce platform connector (Shopify/BigCommerce). The architecture defines where it plugs in. |
| No deployed public URL | Running locally via Docker Compose. No cloud hosting spend. |
| Neo4j GNN is networkx fallback | Full PyG-based GNN fraud ring detection requires Neo4j profile + graph training data. |

---

## Roadmap (Sprint R5 and Beyond)

- **R5**: Extract `recommend.py` into bounded services: `candidate_retriever.py`,
  `recommend_pipeline.py`, `response_normalizer.py`. Scatter-gather scaffold already present.
- **R6**: Swap Ollama to provider-agnostic Claude/GPT-4o mini for sub-2s response in demo.
- **R7**: Real catalog integration (Shopify/BigCommerce connector via existing adapter layer).
- **Security**: Human escalation room (WS wired, state machine incomplete). Decision trace WS
  (`/decisions/{id}/events/ws` — frontend was pointing to wrong path, now fixed).
- **Compliance**: OWASP Agentic AI Top 10 Dec 2025 full mapping, GNN fraud ring with Neo4j.

---

## Documentation

| Doc | Contents |
|-----|----------|
| `docs/COMPLIANCE-MASTER-ACTION-PLAN.md` | 10 CRITICAL + 10 HIGH + 12 MEDIUM items, exact file:line refs, 3-sprint plan |
| `docs/COMPLIANCE-FRAMEWORK-CONTROL-MATRIX.md` | PCI DSS / ISO 27001 / ISO 42001 / GDPR / EU AI Act control coverage matrix |
| `docs/COMPLIANCE-INSIDER-THREAT.md` | 5 detectors, WORM audit, dual-control, prompt hash-lock, SoD |
| `docs/PROD-GRADE-MASTER-ROADMAP.md` | 6-sprint roadmap, all env vars, new files list, architecture before/after |
| `docs/SHOPSQUIRE_DEEP_DIVE_APRIL04_2026.md` | April 2026 comprehensive audit: real vs stub inventory, production gaps, 20-item fix list |

---

## Positioning

ShopSquire occupies a quadrant that has no direct commercial equivalent:

```
                    HIGH SECURITY DEPTH
                            │
            CrowdStrike     │     ShopSquire
            Darktrace       │     (target quadrant)
                            │
────────────────────────────┼────────────────────────────
LOW ECOMMERCE DEPTH         │         HIGH ECOMMERCE DEPTH
                            │
            (generic        │     Shopify / Magento
             chatbots)      │     Salesforce Agentforce
                            │
                    LOW SECURITY DEPTH
```

CrowdStrike and Darktrace have security depth but no e-commerce domain knowledge.
Shopify and Agentforce have e-commerce domain knowledge but treat security as a separate
perimeter concern. ShopSquire's differentiator is security agents running inside the
commerce pipeline — not alongside it.

The killer feature combination: bitemporal decision audit trail + CV triage for return
fraud + in-pipeline security agents. No competitor currently occupies this intersection.

---

*Built in the ANZ market context. AusPost/StarTrack integration and Australian Privacy
Principles compliance are design targets. Cyberstash (ANZ cybersecurity) informed the
threat intelligence layer.*
