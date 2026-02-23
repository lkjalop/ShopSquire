# ShopSquire Platform Assessment — Part 1
## Architecture, Agents, Frontend, Observability & Agentic Platform Comparison

*Assessment Date: 2026-02-22 | Branch: wip/docker-real-env-20260213*

---

## 1. Executive Summary

ShopSquire is a **vertically-specialized, security-first multi-agent e-commerce platform** built on FastAPI + React. It is not a general-purpose agent framework — it is a purpose-built system that embeds agentic intelligence into a real business domain: shopping, complaint triage, supply-chain security, and email threat detection.

The platform is **more production-hardened than most agentic demos** but has **structural gaps as a formal agentic system**: agents are implicit (service-layer functions) rather than explicitly typed, composable units. The compass artifact's vision of atomic, schema-validated, dynamically-injected pipelines is largely aspirational here — the bones exist but the architecture is not yet formalized.

**Verdict by layer:**

| Layer | Maturity | Notes |
|---|---|---|
| Backend API | ★★★★★ | Sophisticated middleware, 89 routers, solid auth |
| Security (Email XDR) | ★★★★★ | Production-grade multi-signal detection |
| CV/OCR Fraud Triage | ★★★★☆ | Strong; missing adversarial robustness testing |
| Agent Architecture | ★★☆☆☆ | Implicit service chains, no typed I/O contracts |
| Frontend (Admin) | ★★★★☆ | 18+ panels, real-time, sophisticated |
| Frontend (Storefront) | ★★★☆☆ | Functional; missing i18n, a11y, error boundaries |
| RAG / Retrieval | ★☆☆☆☆ | Absent; LLM queries are ungrounded |
| Context Engineering | ★★☆☆☆ | Ad-hoc injection; no typed providers |
| Test Coverage | ★★★☆☆ | 297 backend tests; zero frontend unit tests |
| Observability | ★★★★☆ | Prometheus + OTel + Grafana; missing SLO dashboards |
| Cost Optimization | ★★☆☆☆ | Single model, no routing, no caching strategy |

---

## 2. Platform Architecture Overview

### 2.1 Technology Stack

```
Backend:       FastAPI 0.110+ / Python 3.11+ / Uvicorn 0.29+
Database:      PostgreSQL 16 (prod) + SQLite (test)
Cache/PubSub:  Redis 7
ORM:           SQLAlchemy 2.0 + Alembic migrations
Time-series:   TimescaleDB extension on PostgreSQL
Graph:         Neo4j 5.18 (optional, not yet integrated in agents)

ML/Vision:     OpenCV (headless), Pillow, pytesseract, PaddleOCR, pyzbar
Observability: Prometheus, OpenTelemetry (Jaeger export), Grafana
Security:      PyJWT 2.9+, Cryptography 41, email-validator

Frontend:      React 18, Vite, TypeScript (admin), JavaScript (storefront)
Ports:         API :8080, Admin UI :3001, Storefront :5173
Docker:        7-service compose (api, db, redis, sync-worker, prometheus, alertmanager, grafana)
```

### 2.2 Middleware Stack (11 layers, in order)

```
1. SecurityHeadersMiddleware       → HTTP security headers (X-Frame-Options, etc.)
2. WebhookSecurityMiddleware       → HMAC signature + replay prevention for all webhooks
3. IdempotencyMiddleware           → POST/PUT/PATCH idempotency via idempotency_keys table
4. AdminMfaMiddleware              → MFA enforcement for owner/developer routes
5. PciBoundaryMiddleware           → PCI compliance headers
6. ComplianceMiddleware            → Per-request compliance flags + PCI data detection
7. backpressure_middleware         → Rate limiting, concurrency, chaos injection
8. request_logger_middleware       → Test-mode request logging
9. security_observer_middleware    → Security event emission + anomaly detection
10. request_id_middleware          → Request ID generation for tracing
11. metrics_middleware             → Prometheus HTTP metrics
```

The write schema guard inside the middleware enforces allowlists on POST/PUT/PATCH:
- `/api/v1/recommend/interaction` → `{uid, sku, action, surface, trace_id, context}` only
- `/api/v1/cart/items` → `{uid, sku, quantity}` only
- Regex deny on all admin routes: `(system_prompt|developer_override|raw_sql|drop_table|exec_shell)`

### 2.3 Router Inventory (89 registered routers)

Categories:
- **Admin/BI:** admin, admin_bi, admin_analytics, admin_drift, admin_fairness, admin_supply_chain, admin_playbooks, admin_grafana_proxy, admin_dmarc, admin_compliance_reports, admin_compliance_registry, admin_chat_tools, admin_email, admin_inventory, admin_interleaving, admin_grc, admin_storage, admin_webhooks, admin_email_security
- **Commerce:** recommend, cart, orders, payments, checkout (PayPal, Revolut, GooglePay, Afterpay), inventory, pricing, returns, fraud
- **Security:** security_integrations, email_security, email_security_admin, escalation_room, safe_links, rules, tenant_config, webhook_security
- **Email Ingest:** ingest_gmail, ingest_m365, dmarc
- **Decision/Audit:** decisions, decision_trace_events, decision_replay, audit, posthoc, trace_debug, session_memory
- **AI/NLP:** cv, recruiting, scoring, approvals, intent, chat, query_clusters, analytics
- **Misc:** tickets, storage, data_readiness, health, jobs, consumer_signals, voice, vision

### 2.4 Database Schema Topology

The DB uses PostgreSQL search schemas: `oltp, audit, security, public`

Key table groups:
```
Commerce:     orders, order_sessions, draft_orders, products, inventory, customers, payment_methods
Security:     security_events, iam_events, incidents, security_forced_reauth_flags
Email XDR:    email_security_incidents, email_sender_trust, outbound_email_anomalies
Decision:     decision_logs, decision_audits, decision_trace_events
Playbooks:    playbook_runs, playbook_run_steps, playbook_action_executions, playbook_action_dlq
Audit:        audit_log_chain (Merkle root + prev_hash for tamper-evidence)
CV/Returns:   cases, cv_analyses, fraud_image_hashes, return_labels
Fusion:       fusion_scores, evidence_bundles
Compliance:   security_threshold_overrides, partner_scope_baselines, retention_policies
Recruiting:   (managed in recruiting_pipeline service)
Auth:         user_accounts, session_tokens, oauth_identities, oauth_states
Rules:        rule_definitions, tenant_config_overrides
```

**Bitemporal audit model** in decision_logs:
- `valid_from/valid_to` — business time (user-perceived)
- `system_from/system_to` — system time (tamper-evident audit)

This enables "what did the system decide on date X?" queries — critical for compliance.

---

## 3. Agent Inventory & Capability Assessment

ShopSquire has **implicit agents** — service-layer functions that act as specialized reasoners. They are not formally typed units (no `BaseIOSchema`, no `BaseDynamicContextProvider`), but they function as agents in practice. Here is the full inventory:

---

### Agent 1: Chat/Query Agent
**Location:** `routers/chat.py`, `services/nlp_contract.py`
**What it does:** Routes natural language shopping queries to product recommendations, FAQ answers, or escalation
**Inputs:** User message text, session context, PII-scrubbed by storefront
**Outputs:** Product recommendations, text responses, panel routing signals
**Current capabilities:**
- Intent detection (compare, specs, returns, FAQ, security, complaint)
- Regex-based panel routing
- BEC indicator detection for user-submitted text
- Query cluster analytics

**What it SHOULD do (gaps):**
- Use RAG over product catalog — currently ungrounded LLM responses
- Maintain session memory across turns (session_memory router exists but integration unclear)
- Use CacheRAG for FAQs (identical questions shouldn't hit the LLM)
- Confidence-based routing: low-confidence → human escalation automatically

**Security limits that SHOULD be enforced:**
- NEVER allow write operations to DB based on chat content
- NEVER allow PII collection in chat that isn't explicitly user-submitted
- Hard token budget: max 1,000 output tokens per query (protect against prompt extraction attacks)
- Rate limit per session_id, not just IP (session hijacking protection)

---

### Agent 2: Complaint Triage Agent
**Location:** `routers/support_complaints.py`, `routers/cv.py`
**What it does:** Analyzes customer complaints with CV + fraud scoring + trust routing
**Inputs:** Text description, order ID, issue type, uploaded images
**Outputs:** Auto-approval/rejection verdict, playbook selection, escalation decision

**Processing pipeline:**
```
1. ComplaintNLP → intent extraction (return/fraud/quality/warranty)
2. Contract analysis → is_contract_like_text() → legal flag
3. Email/BEC check → validate_email_auth(), detect_bec_indicators()
4. CV analysis → image forensics + serial extraction + OCR
5. FraudScorer → fraud_score (0-1)
6. TrustRoutingAgent → trust_score (0-1), tier
7. Auto-approval decision → based on thresholds in feature_flags.json
8. Playbook selection → select_cv_playbook()
9. Ticketing → TicketingAgent (if high risk)
```

**Security rules (23 rules, CV01-CV26):**
- CV01: duplicate_image_detected (high)
- CV02: serial_mismatch (high)
- CV09: ocr_order_id_mismatch (high)
- CV13: return_window_expired (high)
- CV15: repeat_offender_pattern (high)
- CV21: fraud_score_high (high)
- CV26: counterfeit_indicator (high)

**Auto-approval thresholds (feature_flags.json):**
- Min CV confidence for signed-in: 0.80
- Min CV confidence for guest: 0.85
- Auto-process only for fraud_level: ["minimal", "low"]

**What it SHOULD do (gaps):**
- Cross-reference complaint against known fraud patterns via Graph RAG (product → known fraud schemes)
- Temporal pattern detection: 3 similar complaints in 30 days → automatic escalation
- Multi-image consistency scoring (partially implemented; extend to cross-session comparison)
- Adversarial robustness: test against JPEG adversarial perturbations (current OCR can be confused)

**Security limits:**
- NEVER auto-approve a complaint where serial mismatch is detected (CV02 must be hard block)
- NEVER process images without ingest gate (strictly enforced via strict_binary_ingest_gate)
- Image processing should be sandboxed (prevent decompression bombs / polyglots)
- Max 5 images per complaint; max 50MB total

---

### Agent 3: Email Security Agent (XDR)
**Location:** `security/email_security.py`, `security/email_security_rules.py`, `security/email_security_verdict.py`, `security/email_attachment_intel.py`
**What it does:** Multi-signal email threat detection for BEC, phishing, malware, ransomware, supply-chain compromise

**Detection pipeline:**
```
1. Rule-based indicator extraction:
   - Reply-to mismatch (brand impersonation)
   - Lookalike domain + confusable homoglyphs
   - Suspicious attachments (executable extensions)
   - Bank change requests (BEC pattern)
   - Urgency keywords
   - LOLBins (certutil, powershell -enc, rundll32, bitsadmin, mshta)
   - Ransomware threats ("your files are encrypted", "decrypt key", "bitcoin payment")
   - Data exfiltration ("export customers", "upload to mega")
   - Keylogger/C2/fileless patterns
   - Canary token detection

2. IOC enrichment:
   - Domain reputation (malicious, phishing, C2)
   - IP reputation (botnet, proxy, datacenter)
   - URL sandbox detonation (suspicious behavior)
   - Hash matching (malware family)

3. Attachment forensics:
   - PDF metadata (producer/creator), embedded files, compression artifacts
   - Bank field extraction: ABN, BSB, SWIFT, invoice, PO, GRN, receipt numbers
   - Vendor baseline matching: compare proposed bank fields vs known baseline
   - Homoglyph normalization for spoofed documents

4. Verdict computation:
   - BEC warning: ≥2 indicators
   - BEC error: ≥3 indicators
   - IOC warning: ≥1 denylisted IOC
   - IOC error: ≥2 denylisted IOCs
   - MITRE ATT&CK tagging (T1566.001, T1566.002, T1218, etc.)

5. Playbook orchestration:
   - Block sender, quarantine, forward to MSSP, create ticket, force reauth
   - DLQ for failed actions
```

**What it SHOULD do (gaps):**
- **Thread analysis:** Track reply-chain hijacking across sessions (prior_reply_chain_id exists but chain analysis depth unclear)
- **Behavioral baseline per supplier:** Track normal email patterns per vendor (timing, frequency, typical content) — deviation is suspicious
- **Clustering:** Use embedding similarity to cluster similar BEC campaigns across tenants (shared threat intelligence)
- **Feedback loop to LLM tuning:** analyst_verdict corrections feed threshold recomputation, but not yet used for few-shot prompting

**Security limits:**
- NEVER auto-remediate (block/quarantine) without playbook execution trace
- NEVER trust SPF/DKIM/DMARC results from untrusted mail relay headers
- Attachment processing MUST run in isolation (detonation sandbox, not inline)
- LLM assist output is explicitly non-authoritative (good — keep it that way)

---

### Agent 4: Trust Routing Agent
**Location:** `services/trust_routing.py`
**What it does:** Computes customer trust score; routes to appropriate workflow tier

**Score formula:**
```
Base: 0.5
+0.10 if account_age > 365 days
+0.15 if loyalty_tier in (gold, platinum)
+0.10 if total_orders > 10
+0.05 if email_verified AND phone_verified
-0.20 if return_rate > 30%
-0.30 if fraud_flags > 0
-0.15 if returns_last_30_days > 3
Final: clamp(0.0, 1.0)
```

**Routing tiers:**
```
≥0.80 → high_trust  → auto-approve up to $500
≥0.60 → medium_trust → auto-approve up to $200
≥0.40 → guarded     → auto-approve up to $50
<0.40  → manual_review → $0 auto-approve
<0.35  → force_reauth (via security_forced_reauth_flags)
```

**Gaps:**
- Score is purely rule-based with static weights — no ML model
- No temporal decay: fraud flags from 3 years ago should have lower weight
- No cross-platform signals (shipping fraud networks, known bad actors)
- Score manipulation risk: sophisticated attackers could deliberately build trust over time

**Security limits:**
- force_reauth decision must NEVER be skippable by any client parameter
- Trust score must be computed server-side; never accept from client
- fraud_flags must be admin-settable only, never cleared automatically

---

### Agent 5: Security-Aware LLM Wrapper
**Location:** `services/security_aware_llm.py`
**What it does:** Wraps all LLM calls with pre/post security checks

**Pipeline:**
```
1. Pre-check: sanitize_ocr_text() → removes injection patterns from prompt
2. Context sanitization: recursively clean ocr_text, extracted_text fields
3. QR URL policy: enforce_qr_url_allowlist() on all URLs in context
4. Payload analysis: analyze_payload() via security observer
5. LLM call (if clean)
6. Post-check: re-analyze response for malicious content
7. Return response + security metadata (blocked, reasons, sanitization stats)
```

**Blocking rule:** If pre or post check severity ≥ "high" → return blocked response, no LLM output

**Gaps:**
- No token budget enforcement (prevent prompt extraction via long outputs)
- No output schema validation (LLM could return arbitrary structure)
- No model-specific guardrails (depends on upstream provider safety filters)
- Missing: constitutional AI / self-critique loop for high-stakes decisions

**Security limits:**
- HARD block: LLM must NEVER be given raw user PII (order emails, phone numbers)
- HARD block: LLM output must NEVER contain raw SQL, shell commands, or code that gets executed
- LLM tool use (if enabled) must be restricted to read-only operations
- Max context window per call: enforce to prevent prompt stuffing attacks

---

### Agent 6: Intake Gate Agent
**Location:** `services/intake_gate.py`
**What it does:** Binary go/no-go for all file uploads before any processing

**Checks:**
- File magic byte validation (PDF, ZIP, PNG, JPEG, GIF only)
- Extension blacklist: `.exe .dll .scr .bat .ps1 .vbs .hta .msi .jar .iso`
- Archive bomb detection (ZIP/TAR with size limits: 50MB file, 500MB uncompressed)
- QR URL allowlist (localhost, 127.0.0.1 — needs production config)
- Prompt injection regex: "ignore previous", "system prompt", "jailbreak", etc.
- LOLBins / PowerShell script detection
- OCR text sanitization (removes injection patterns from extracted text)

**Gaps:**
- QR allowlist default is dev-only (`localhost, 127.0.0.1`) — MUST be overridden in production
- No YARA rule integration for malware detection
- No sandboxed decompression (archive bomb check is in-process — risk of OOM)
- PDF polyglot detection missing (valid PDF that is also a valid ZIP)

---

### Agent 7: Decision Logging Agent
**Location:** `services/decision_log.py`
**What it does:** Bitemporal audit trail for all agent decisions

**Capabilities:**
- Full bitemporal model (valid_time + system_time) — enables temporal audit queries
- Per-trace event sequencing with in-memory cache (256 events/trace)
- Outbox pattern for webhook dispatch (async, Redis stream or DB)
- Pub-sub broadcast for real-time trace UI streaming
- Trace contracts validation via `apply_trace_contract()`

**Gaps:**
- In-memory cache (256 events/trace) lost on pod restart — should be Redis-backed
- No compression on trace payload (large traces hit DB fast)
- No trace retention/expiry policy (old traces accumulate)

---

### Agent 8: Playbook Orchestration Agent
**Location:** Referenced in `email_security.py`, `support_complaints.py`, `admin_email_security.py`
**What it does:** Executes typed remediation action sequences

**Capabilities:**
- `start_playbook_run()` → creates execution record
- `execute_typed_actions()` → runs block/quarantine/forward/ticket/force_reauth
- `complete_playbook_run()` → records outcome
- Playbook action DLQ for failed actions + scheduler for reprocessing
- Idempotency: each action has an `idempotency_key`

**Gaps:**
- No action dependency graph (actions execute sequentially; parallel actions need explicit dependency declaration)
- No action rollback for partially-completed playbooks
- DLQ reprocessing scheduler alerting if backlog grows

---

### Agent 9: Escalation Room Agent
**Location:** `routers/escalation_room.py`
**What it does:** Real-time human-in-the-loop incident room

**Capabilities:**
- Dual-channel: WebSocket for staff, SSE/EventSource for buyers
- Token-based channel access (buyer token + staff token, configurable TTL)
- In-memory subscriber dict with asyncio.Queue broadcast
- Fallback storage to filesystem if Redis unavailable

**Gaps:**
- In-memory subscriber dict → not horizontally scalable (sticky sessions needed or Redis pub-sub)
- No message persistence by default (if subscriber disconnects, messages lost)
- Buyer public endpoint allows unauthenticated access on localhost (demo only — production must enforce)

---

### Agent 10: Recruiting Pipeline Agent
**Location:** `routers/recruiting.py`, `services/recruiting_pipeline.py`, `schemas/recruiting.py`
**What it does:** Resume parsing, candidate triage, ranking, fairness audit

**Capabilities:**
- Regex + SimpleEmbeddings for skill extraction and canonicalization
- Feature-weighted scoring: location match, years experience, skill overlap
- Fairness audit: disparate impact ratio per demographic group (80% rule)
- Feedback loop: corrections feed aggregate metrics

**Assessment:** This module is **architecturally sound** but **out of scope** for an e-commerce shopping assistant. It appears to be a proof-of-concept for the agent framework (demonstrating decision logging, fairness auditing, typed schemas). Consider spinning it out or clearly namespacing it as an enterprise HR sub-product.

**Security limits:**
- Fairness audit flags MUST be surfaced to admin, never suppressed
- Candidate PII (email, phone) must be encrypted at rest
- Reject decisions must be logged with full feature contribution trace (legal requirement in most jurisdictions)

---

## 4. Frontend Capabilities

### 4.1 Storefront (`:5173`)

**Components and capabilities:**

| Component | Capabilities | Gaps |
|---|---|---|
| Chat Panel | Floating FAB, voice input (WebKit SpeechRecognition), PII detection (Luhn, SSN, bank, email) | No session continuity across page reload |
| Product Grid | Grid/list/compare/cart/faq/security/cv panel modes | No skeleton loading states |
| RightPanelExtras | CV upload, image analysis, FAQ KB, advanced admin controls | No drag-to-reorder images |
| DecisionTrace Modal | Draggable/resizable, 3x streaming (WS/SSE/poll), 4 tabs (Events/Summary/Security Matrix/Raw) | |
| EscalationRoom | Real-time staff↔buyer chat, dual-stream, auto-scroll | No offline indicator |
| Health Monitor | /healthz polling every 5s with latency display | |

**PII Detection (client-side, pre-send):**
- Credit card numbers (Luhn algorithm validation)
- SSNs (regex)
- Bank account numbers (regex)
- Email addresses (regex)
User is warned before sending detected PII to backend — good UX security pattern.

**Backend integration endpoints used by storefront:**
```
/api/v1/chat/query
/api/v1/orchestrate
/api/v1/support/complaints/submit
/api/v1/incidents/escalate
/api/v1/security/playbooks/cv
/api/v1/decisions/{traceId}/events/ws
/api/v1/decisions/{traceId}/events/stream
/healthz
```

### 4.2 Admin Dashboard (`:3001`)

18+ panels with role-based access:

| Panel | Roles | Capabilities |
|---|---|---|
| Merchant BI Dashboard | merchant, owner, developer | Timeseries charts, security heatmaps, geo/ASN trends |
| Decision Control Room | all | Audit trace replay + explain |
| Security Monitor | owner, developer | Real-time threat tracking |
| Email XDR Triage | developer, owner | Incident list, investigation, bulk label, playbook execution |
| CV Incidents | merchant, owner | Return evidence review by SKU |
| Escalations Console | merchant, owner, developer | Live incident rooms, status updates, staff token issuance |
| Playbook Editor | developer, owner | Validate/publish/rollback/dry-run/diff |
| Rules Admin | all | Database-backed rule engine UI |
| GRC | owner | Risk register, control mapping, fingerprint threat monitoring |
| Compliance | owner | SOC2/ISO/GDPR evidence bundles |
| Analytics | all | Time-series performance dashboard |
| Grafana (embedded) | developer, owner | Full observability integration |

**API Key handling (gap):** Keys stored in `localStorage` — vulnerable to XSS. Should use `httpOnly` cookies or session-scoped memory only.

### 4.3 Frontend Gaps Summary

```
Critical:
  - Zero Jest/Vitest unit tests for any React component
  - API keys in localStorage (XSS risk)
  - No React error boundaries (unhandled errors crash entire UI)

Important:
  - No i18n (internationalization)
  - No ARIA labels / keyboard navigation (accessibility failure)
  - No Web Vitals / performance monitoring
  - No service worker / offline fallback
  - No CSP headers enforcement from Vite dev config

Nice-to-have:
  - No component library (shadcn/ui or similar) — custom HTML elements everywhere
  - No global state management (React Context or Zustand) — useState everywhere
  - No visual regression testing (Playwright visual comparison not set up)
```

---

## 5. Parallel Agent Swarms & Team Patterns

### 5.1 Current State

ShopSquire's "multi-agent" behavior is **sequential service chaining**, not true parallel agent swarms:

```
User request
  → middleware stack (11 layers, sequential)
    → router handler
      → service A (NLP)
        → service B (CV/fraud)
          → service C (trust routing)
            → service D (playbook)
              → response
```

There is no parallel agent dispatch. When complaint triage runs, all sub-services execute in series.

### 5.2 Where Parallelism Would Help

Three high-value parallelization opportunities exist:

**Opportunity 1: Complaint triage**
```
Current (sequential, ~3-5s total):
  NLP intent → CV analysis → fraud scoring → trust routing

Proposed (parallel, ~1.5s):
  NLP intent ──────────────────────────────┐
  CV analysis (image forensics) ──────────→ Merge → verdict
  Fraud score (history lookup) ────────────┘
```

**Opportunity 2: Email security**
```
Current (sequential):
  Rule extraction → IOC enrichment → attachment forensics → verdict

Proposed (parallel):
  Rule extraction ────────────────┐
  IOC enrichment ─────────────────→ Merge → verdict
  Attachment forensics ───────────┘
```

**Opportunity 3: Multi-product query**
```
When user asks about multiple products, spawn one retrieval agent per product.
Currently: single LLM call with all products in context (context pollution).
Proposed: parallel retrieval agents → merge → single answer generation.
```

### 5.3 Parallelization Pattern to Adopt

The compass artifact recommends: **deterministic pipeline backbone + strategic parallel agent injection**.

For ShopSquire, this maps to:
```python
# Typed I/O contracts (currently missing)
class ComplaintTriageInput(BaseIOSchema):
    complaint_text: str
    order_id: str
    images: List[ImageMeta]
    customer_id: Optional[str]

class ComplaintTriageOutput(BaseIOSchema):
    intent: ComplaintIntent
    fraud_score: float
    trust_tier: TrustTier
    cv_verdict: CVVerdict
    recommended_action: Action
    trace_id: str

# Parallel execution (currently sequential)
async with asyncio.TaskGroup() as tg:
    nlp_task = tg.create_task(nlp_agent.run(input))
    cv_task = tg.create_task(cv_agent.run(input))
    fraud_task = tg.create_task(fraud_agent.run(input))

# Typed merge (currently ad-hoc dict merging)
result = merge_agent.run(ComplaintMergeInput(
    nlp=nlp_task.result(),
    cv=cv_task.result(),
    fraud=fraud_task.result()
))
```

**Latency impact:** Parallelizing the three independent sub-tasks in complaint triage reduces wall-clock time from ~3-5s to ~1.5s (bottleneck is slowest task). Zero added inference cost — same models, same calls, just concurrent.

---

## 6. Decision Trace & Observability

### 6.1 Decision Trace (existing, well-executed)

The decision trace system is **one of the strongest parts of the platform**:
- Three streaming modes: WebSocket → SSE → polling (graceful degradation)
- MITRE ATLAS + OWASP LLM Top 10 + STRIDE + PASTA security matrix
- DREAD scoring + CVSS visualization
- Bitemporal audit with post-hoc outcome recording
- Detached window mode for multi-monitor analyst workflows
- Raw JSON dump tab for developer debugging

This is **not common** in commercial agentic platforms. Most platforms (LangSmith, LangFuse, Weights & Biases) require separate observability tooling. ShopSquire has it embedded in the product.

### 6.2 Observability Stack

```
Prometheus   → metrics scraping (decisions, complaints, email incidents, queries)
OpenTelemetry → distributed trace context (Jaeger export)
Grafana      → dashboards (admin panel integration)
AlertManager → Slack/PagerDuty stubs
Structured logging → request IDs + correlation IDs
```

**Gap:** No SLO (Service Level Objective) dashboards. Prometheus rules exist but no error budget burn rate alerts defined.

### 6.3 Trace Contract Validation

`trace_contracts.py` validates event payloads against canonical schemas per event type:
- `incident_created`: `{incident_id, severity, title, description, created_at}`
- `incident_message`: `{incident_id, message, author_type: buyer|staff, timestamp}`
- `decision_logged`: `{agent_name, decision_id, policy_version, outcome}`

This is the **partial implementation** of what the compass artifact calls "typed schemas." It validates trace events but not agent I/O boundaries.

---

## 7. Test Infrastructure

### 7.1 Coverage

```
Total test files: 297 Python tests across 17 categories
Frontend tests: 0 (zero Jest/Vitest files)
```

| Category | Count | Notes |
|---|---|---|
| API tests | ~60 | Strong coverage of security endpoints |
| Security/redteam | ~20 | Prompt injection, jailbreak, OWASP LLM Top 10 |
| E2E (Playwright) | ~5 | Browser automation against live stack |
| Email security | ~10 | BEC, attachment forensics, regression |
| CV/Returns | ~15 | Image upload, adversarial returns |
| Compliance | ~8 | Decision log audit, GRC exports |
| RAG evals | ~3 | RAGAS baseline (but RAG barely exists!) |
| Recruiting | ~5 | New, thin coverage |
| Load | Unknown | Directory exists, coverage unclear |

### 7.2 Notable Test Patterns

- `test_security_prompt_injection_endpoints.py` — direct injection attacks
- `test_security_indirect_prompt_injection.py` — second-order injection
- `test_security_jailbreak_patterns.py` — jailbreak detection
- `test_security_llm_top10.py` — OWASP LLM Top 10 coverage
- `test_interleaving_controller.py` — interleaving experiments (feature exists!)
- `test_tool_budget_enforcement.py` — tool call budget enforcement
- `test_ragas_baseline.py` — retrieval quality eval (aspirational given RAG absence)

### 7.3 Test Infrastructure Gaps

```
Frontend: No component unit tests (critical gap for React app with complex state)
Load:     Load test existence unclear; no k6 or Locust config visible
Visual:   No Playwright visual regression (screenshot comparison)
Contract: No Pact/contract testing between frontend and API
CI/CD:    No .github/workflows observed (no automated test gate)
```

---

## 8. Comparison to Other Agentic Platforms

### 8.1 Against General-Purpose Frameworks

| Dimension | ShopSquire | CrewAI | LangGraph | AutoGen | OpenAI Swarm |
|---|---|---|---|---|---|
| Agent typing | Implicit service functions | Role-based agents | State graph nodes | Actor model | Stateless agents |
| I/O contracts | Partial (trace events only) | Pydantic + structured output | State schema | Message types | Ad-hoc dicts |
| Parallelism | Sequential only | Strong (Crews + Flows) | Strong (parallel dispatch) | Async message passing | Minimal |
| Observability | Embedded + production-grade | LangSmith integration | LangSmith integration | Azure Monitor | None |
| Domain specialization | Deep (e-commerce + security) | Generic | Generic | Generic | Generic |
| Security controls | Production-grade | Minimal | Minimal | Minimal | None |
| Playbook orchestration | Yes (full DLQ + retry) | No | Partial (checkpointing) | No | No |
| Human-in-the-loop | Real-time escalation room | Callback hooks | Interrupt/resume | ConversableAgent | Handoff only |
| Email XDR | Built-in | Not applicable | Not applicable | Not applicable | Not applicable |
| CV/OCR fraud | Built-in | Not applicable | Not applicable | Not applicable | Not applicable |
| Compliance | SOC2/GDPR/PCI built-in | None | None | Azure compliance | None |
| Fairness audits | Built-in (recruiting) | None | None | None | None |

**ShopSquire's unique position:** No general-purpose agent framework comes close on security controls, compliance features, or domain-specific capabilities. The platform is essentially **CrewAI + LangGraph + LangFuse + email security + CV fraud + compliance** in a single vertical deployment.

**ShopSquire's weakness vs those frameworks:** Formal agent composition. CrewAI, LangGraph, and AutoGen all have cleaner abstractions for defining agents as composable units with typed contracts. ShopSquire's agents are embedded in service functions — powerful but not reusable across domains.

### 8.2 Against Commercial Vertical Platforms

| Dimension | ShopSquire | Salesforce Agentforce | Microsoft Copilot Studio | Zendesk AI |
|---|---|---|---|---|
| Open source | Yes | No | No | No |
| Customization | Full code access | Limited (flows) | Limited (flows) | Limited (macros) |
| Email XDR | Built-in | Partner integration | Azure Sentinel | No |
| CV/OCR fraud | Built-in | No | No | No |
| Decision audit | Bitemporal + Merkle | Basic logging | Basic logging | Basic logging |
| Multi-tenant | Yes | Yes | Yes | Yes |
| Self-hosted | Yes | No (SaaS only) | Hybrid | No |
| Cost | Infrastructure only | $75-$2/action | Per-message pricing | Per-seat |

**ShopSquire is genuinely differentiated** on audit depth, security integration, and self-hosted flexibility. The platform competes with enterprise SIEM + e-commerce helpdesk combinations at a fraction of the cost.

---

## 9. TimescaleDB Assessment

TimescaleDB is referenced in:
- `admin.py` → `/api/v1/admin/db/ensure-timescale` endpoint
- `admin.py` → `/api/v1/admin/db/readiness` checks Timescale status

**Current usage:** Bootstrapped but underutilized. The `ensure-timescale` endpoint creates the extension, but time-series queries in `admin_bi.py` use standard SQL (`date_trunc` / `substr`) rather than TimescaleDB-native functions.

**What TimescaleDB enables that you're not using:**
```sql
-- Continuous aggregates (auto-refresh, no manual ETL)
CREATE MATERIALIZED VIEW orders_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', created_at) AS bucket,
       count(*) AS order_count,
       sum(amount_cents) AS revenue_cents
FROM orders
GROUP BY bucket;

-- Compression (90%+ space savings for cold data)
ALTER TABLE decision_logs SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'tenant_id,agent_name'
);

-- Data retention policy (auto-drop old partitions)
SELECT add_retention_policy('decision_logs', INTERVAL '2 years');
```

**Recommendation:** Convert `decision_trace_events`, `security_events`, `email_security_incidents`, and `decision_logs` to TimescaleDB hypertables. This eliminates the need for manual partitioning and enables real-time dashboards at scale without Kafka.

---

*Continued in Part 2: Security Threat Model, Gaps, Compass Artifact Analysis, RAG Recommendations, Over-Engineering Assessment.*
