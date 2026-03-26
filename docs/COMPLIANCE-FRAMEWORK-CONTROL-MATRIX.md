# ShopSquire — Compliance Framework Control Matrix
**Date:** 2026-03-26
**Purpose:** Maps every major compliance requirement to the specific ShopSquire code, config, or process that satisfies (or must satisfy) it.
**Frameworks:** PCI DSS 4.0, ISO 27001:2022, ISO 42001:2023, GDPR, EU AI Act, NIST RMF (SP 800-37r2), NIST AI RMF, Australian Privacy Act 1988 (APPs)

**Status Legend:** ✅ Implemented | ⚠️ Partial | ❌ Not Implemented | 🔧 In Progress

---

## PCI DSS 4.0 — Control Coverage

| Requirement | Control | ShopSquire Implementation | File:Line | Status |
|---|---|---|---|---|
| Req 1.2 — Network controls | Egress allowlist | `config/security/egress_allowlist.txt` + `security/egress_allowlist.py` | Multiple | ⚠️ Partial (no startup assertion) |
| Req 3.3 — Protect stored PAN | No PAN storage | Payment tokenisation via Stripe/PayPal | `routers/payments.py` | ⚠️ Verify Stripe token only, no raw PAN |
| Req 3.5 — PAN masking in displays | DLP scrubbing | `security/dlp_export.py` | `dlp_export.py:1` | ⚠️ Scrubs secrets, not PAN patterns |
| Req 4.2 — Encrypt PAN in transit | TLS enforced | HSTS + mTLS middleware | `security/tls_fingerprint_middleware.py` | ⚠️ Off by default in local/dev |
| Req 5.2 — Anti-malware | YARA scanning | `security/yara_email_scan.py` | `yara_email_scan.py` | ✅ |
| Req 6.2 — Secure software development | Secure SDLC | Supply chain scanner, SBOM | `services/supply_chain_security.py` | ⚠️ No CI gate |
| Req 6.3.2 — Software inventory | SBOM | `services/sbom_scheduler.py` | `sbom_scheduler.py` | ⚠️ Not blocking in CI |
| Req 6.4.3 — CSP for payment pages | CSP headers | **NOT IMPLEMENTED** | `main.py` missing | ❌ CRIT-07 |
| Req 7.2 — Least privilege | RBAC | `security/rbac.py`, `rbac_policy.json` | `security/rbac.py:1` | ⚠️ Policy exists, not enforced at routes |
| Req 8.2 — User identification | Auth + JWT | `routers/auth.py` | `auth.py:1` | ✅ |
| Req 8.2.8 — Session idle timeout | Frontend timeout | **NOT IMPLEMENTED** | `AdminDashboard.tsx` missing | ❌ MED-10 |
| Req 8.4 — MFA for admin | TOTP MFA | `security/admin_mfa.py` | `admin_mfa.py` | ⚠️ Verify mandatory enforcement |
| Req 8.6.1 — Service accounts | Per-service accounts | **NOT IMPLEMENTED** | `docker-compose.yml` | ❌ IT-PREV-03 |
| Req 10.2 — Audit logs | Audit chain | `security/audit_chain.py` | `audit_chain.py:1` | ⚠️ HMAC hardcoded (CRIT-01) |
| Req 10.3 — Protect audit logs | Immutable logs | WORM archive (partial) | `audit_chain.py` | ⚠️ Archive not wired |
| Req 10.5.1 — Time synchronisation | NTP sync | Docker / OS level | `docker-compose.yml` | ⚠️ Not explicitly configured |
| Req 10.7 — Alert on log failures | Audit failure alerting | **NOT IMPLEMENTED** | `audit_chain.py` | ❌ |
| Req 11.3 — External penetration test | Pentest | **NOT DONE** | Process | ❌ |
| Req 12.3 — Risk assessment | Authority matrix | **NOT IMPLEMENTED** | `policy/action_authority_matrix.py` missing | ❌ CRIT-05 |
| Req 12.10 — Incident response | IR plan + ticketing | `services/ticketing.py`, `routers/incident.py` | Multiple | ⚠️ No SLA enforcement (HIGH-08) |

---

## ISO 27001:2022 — Control Coverage

| Control | Description | ShopSquire Implementation | File:Line | Status |
|---|---|---|---|---|
| A.5.2 — Information security policies | Policy documents | `docs/` directory | `docs/` | ⚠️ Technical docs exist, formal ISMS policy missing |
| A.5.7 — Threat intelligence | Threat feeds | `security/threat_feed_client.py`, `security/threat_intel_store.py` | Multiple | ✅ |
| A.5.15 — Access control | RBAC + JWT | `security/rbac.py`, `security/auth.py` | Multiple | ⚠️ Policy not enforced at routes |
| A.5.17 — Authentication information | Vault + secrets manager | `security/secrets_store.py`, `services/secrets_manager.py` | Multiple | ⚠️ Vault optional, env var fallback |
| A.5.18 — Access rights review | Quarterly review | **NOT DOCUMENTED** | Process | ❌ IT-PROC-01 |
| A.5.23 — Security for cloud services | Egress control + DLP | `security/egress_allowlist.py`, `security/dlp_export.py` | Multiple | ⚠️ PII patterns missing |
| A.5.24 — Information security incident planning | IR plan | `routers/incident.py`, `services/ticketing.py` | Multiple | ⚠️ No SLA, no severity model in code |
| A.5.26 — Response to incidents | Escalation room | `routers/escalation_room.py` | `escalation_room.py` | ⚠️ Incomplete (noted in MEMORY) |
| A.5.33 — Protection of records | Data retention | **NOT IMPLEMENTED** | Multiple | ❌ No retention/deletion schedules |
| A.6.3 — Information security awareness | Training program | **NOT DOCUMENTED** | Process | ❌ |
| A.7.11 — Physical security | Docker secrets / Vault | `docker-compose.yml` | `docker-compose.yml` | ⚠️ Vault not mandatory |
| A.8.2 — Privileged access rights | Admin role checks | `security/auth.py`, `security/rbac.py` | Multiple | ⚠️ Not enforced per-resource |
| A.8.4 — Access to source code | Git access controls | **NOT CONFIGURED** | `.github/CODEOWNERS` missing | ❌ IT-PREV-02 |
| A.8.5 — Secure authentication | MFA for admin | `security/admin_mfa.py` | `admin_mfa.py` | ⚠️ Not mandatory |
| A.8.8 — Management of technical vulnerabilities | Vulnerability scanning | `services/vuln_scanner.py`, `routers/vuln_scan.py` | Multiple | ✅ |
| A.8.9 — Configuration management | Security hardening env | `config/security/security-hardening.env.example` | `security-hardening.env.example` | ⚠️ Template only, not enforced |
| A.8.10 — Information deletion | DSR erasure | **NOT IMPLEMENTED** | `routers/privacy.py` | ❌ MED-11 |
| A.8.11 — Data masking | DLP | `security/dlp_export.py` | `dlp_export.py` | ⚠️ Secrets only, no PII |
| A.8.15 — Logging | Audit chain + SIEM | `security/audit_chain.py`, `security/siem_adapter.py` | Multiple | ⚠️ HMAC hardcoded |
| A.8.16 — Monitoring | Prometheus + Grafana | `observability/metrics.py`, `monitoring/dashboards/` | Multiple | ✅ |
| A.8.20 — Networks security | TLS + mTLS | `security/tls_fingerprint_middleware.py` | `tls_fingerprint_middleware.py` | ⚠️ Off in dev |
| A.8.23 — Web filtering | URL guard + safe links | `security/url_guard.py`, `routers/safe_links.py` | Multiple | ✅ |
| A.8.24 — Use of cryptography | Audit HMAC + JWT | `security/audit_chain.py`, `routers/auth.py` | Multiple | ⚠️ Hardcoded HMAC key |
| A.8.28 — Secure coding | Supply chain + SBOM | `services/supply_chain_security.py` | `supply_chain_security.py` | ⚠️ No CI gate |

---

## ISO 42001:2023 — AI Management System Controls

| Clause | Description | ShopSquire Implementation | File:Line | Status |
|---|---|---|---|---|
| 4.1 — Understanding the org | AI system context | **NOT DOCUMENTED** | Missing | ❌ HIGH-01 |
| 4.2 — Interested parties | AI stakeholder register | **NOT DOCUMENTED** | Missing | ❌ |
| 5.2 — AI policy | AI use policy | **NOT DOCUMENTED** | Missing | ❌ |
| 6.1 — Risks and opportunities | AI risk register | `docs/SHOPSQUIRE_PLATFORM_DEEP_DIVE_2026.md` | `docs/` | ⚠️ Informal only |
| 6.1.2 — Risk classification | High-risk AI identification | **NOT FORMAL** | Missing `model_registry.json` | ❌ HIGH-01 |
| 6.1.4 — DPIA / AI impact assessment | DPIA for fraud scoring | **NOT DONE** | Missing | ❌ HIGH-05 |
| 6.2 — AI objectives | Performance baselines | `monitoring/dashboards/accuracy.json` | `accuracy.json` | ⚠️ No alert thresholds |
| 8.3 — AI system performance | Answer quality monitoring | `services/answer_quality.py` | `answer_quality.py` | ⚠️ No drift alerts |
| 8.4 — Human oversight | Kill switches | **NOT IMPLEMENTED** | Missing `kill_switch.py` | ❌ HIGH-04 |
| 8.5 — Change management | Model change process | **NOT DOCUMENTED** | Missing | ❌ MED-06 |
| 8.6 — AI system documentation | Model registry | **NOT IMPLEMENTED** | Missing `model_registry.json` | ❌ HIGH-01 |
| 9.1 — Monitoring | Model drift alerting | **NOT IMPLEMENTED** | Missing alert rules | ❌ MED-09 |
| 9.2 — Internal audit | AI audit cadence | **NOT DOCUMENTED** | Process | ❌ |
| 10.2 — Nonconformity | Incident/bug process | `services/ticketing.py` | `ticketing.py` | ⚠️ No SLA |

---

## GDPR — Control Coverage

| Article | Requirement | ShopSquire Implementation | File:Line | Status |
|---|---|---|---|---|
| Art 5(1)(a) — Lawfulness | Lawful basis documented | **NOT DOCUMENTED** | Missing `ROPA.md` | ❌ MED-03 |
| Art 5(1)(b) — Purpose limitation | Purpose-bound retrieval | `services/semantic_cache.py` | `semantic_cache.py` | ⚠️ Not formally documented |
| Art 5(1)(c) — Data minimisation | PII scrubbing before LLM | **NOT IMPLEMENTED** | `dlp_export.py` | ❌ CRIT-06 |
| Art 5(1)(e) — Storage limitation | Retention schedules | **NOT IMPLEMENTED** | Missing | ❌ |
| Art 13/14 — Transparency | Privacy notice | **NOT PRESENT** | `ui_storefront.py` | ❌ |
| Art 17 — Right to erasure | DSR erasure endpoint | **NOT IMPLEMENTED** | `routers/privacy.py` | ❌ MED-11 |
| Art 20 — Data portability | DSR export | **NOT IMPLEMENTED** | `routers/privacy.py` | ❌ MED-11 |
| Art 22 — Automated decisions | Human review path | **PARTIAL** | `escalation_room.py` (incomplete) | ⚠️ HIGH-04 |
| Art 25 — Privacy by design | PII scrubbing + audit | `security/dlp_export.py` | `dlp_export.py` | ⚠️ Secrets only |
| Art 30 — Records of processing | RoPA | **NOT DOCUMENTED** | Missing | ❌ MED-03 |
| Art 32 — Security of processing | Encryption + audit | `security/backup_encrypt.py`, `audit_chain.py` | Multiple | ⚠️ |
| Art 33 — Breach notification | IR plan + 72h notification | **NOT DOCUMENTED** | Process | ❌ |
| Art 35 — DPIA | DPIA for AI decisions | **NOT DONE** | Missing | ❌ HIGH-05 |
| Art 44–49 — Transfers | Data residency gate | **NOT IMPLEMENTED** | Missing `data_residency.py` | ❌ CRIT-10 |

---

## EU AI Act — Control Coverage

| Article | Requirement | ShopSquire Implementation | Status |
|---|---|---|---|
| Art 6 — Classification of high-risk AI | Fraud scoring, CV return triage = likely high-risk | **NOT CLASSIFIED** | ❌ HIGH-01 |
| Art 9 — Risk management system | AI risk register | Informal in `docs/` | ⚠️ |
| Art 10 — Data governance | Training data documentation | **NOT DOCUMENTED** | ❌ |
| Art 11 — Technical documentation | Model cards / registry | **NOT IMPLEMENTED** | ❌ HIGH-01 |
| Art 12 — Logging | Audit chain with provenance | `security/audit_chain.py` | ⚠️ HMAC issue |
| Art 13 — Transparency | Explainable AI output | `services/cv_explain.py`, `DecisionTrace.tsx` | ⚠️ Not always surfaced |
| Art 14 — Human oversight | Kill switches, dual control | **NOT IMPLEMENTED** | ❌ HIGH-04 |
| Art 15 — Accuracy, robustness, security | Adversarial testing | `security/redteam/` | ⚠️ Exists, not systematised |
| Art 16 — Obligations of providers | Technical documentation | **NOT DOCUMENTED** | ❌ |
| Art 17 — Quality management | ISO 42001-equivalent QMS | **NOT IMPLEMENTED** | ❌ |
| Art 62 — Post-market monitoring | Accuracy/drift dashboards | `monitoring/dashboards/accuracy.json` | ⚠️ No alert thresholds |

---

## NIST AI RMF — Function Coverage

| Function | Category | ShopSquire Implementation | File:Line | Status |
|---|---|---|---|---|
| GOVERN | 1.1 — AI risk policies | AI policy document | **MISSING** | ❌ |
| GOVERN | 1.2 — Authority matrix | Policy decision engine | **MISSING** | ❌ CRIT-05 |
| GOVERN | 2.1 — Acceptable use | AUP for AI agents | **MISSING** | ❌ IT-PROC-02 |
| GOVERN | 4.2 — Human oversight | Kill switches | **MISSING** | ❌ HIGH-04 |
| MAP | 1.5 — Identify AI risks | Risk register | Informal docs | ⚠️ |
| MAP | 2.1 — Classify AI system | Model registry | **MISSING** | ❌ HIGH-01 |
| MEASURE | 1.1 — Metrics defined | Prometheus metrics | `observability/metrics.py` | ✅ |
| MEASURE | 2.5 — Bias testing | Fairness router | `routers/admin_fairness.py` | ⚠️ Not systematised |
| MEASURE | 2.8 — Model drift | Drift monitoring | **MISSING alert rules** | ❌ MED-09 |
| MANAGE | 1.3 — Egress control | Egress allowlist | `security/egress_allowlist.py` | ⚠️ No startup assertion |
| MANAGE | 2.2 — Incident response | Ticketing + IR | `services/ticketing.py` | ⚠️ No SLA |
| MANAGE | 3.1 — Risk treatment | Autonomy kill switch | **MISSING** | ❌ HIGH-04 |

---

## Australian Privacy Act (APPs) — Control Coverage

| APP | Requirement | ShopSquire Implementation | Status |
|---|---|---|---|
| APP 1 — Open management | Privacy policy | **NOT PUBLISHED** | ❌ |
| APP 3 — Collection | Minimise collection | PII scrubbing pre-LLM | ❌ CRIT-06 |
| APP 5 — Notification | Collection notification | **NOT IMPLEMENTED** | ❌ |
| APP 6 — Use/disclosure | Purpose limitation | Semantic cache purpose binding | ⚠️ |
| APP 7 — Direct marketing | Opt-out mechanism | **NOT DOCUMENTED** | ❌ |
| APP 8 — Cross-border disclosure | Data residency gate | **NOT IMPLEMENTED** | ❌ CRIT-10 |
| APP 11 — Security | Encryption + audit chain | `security/backup_encrypt.py`, `audit_chain.py` | ⚠️ HMAC hardcoded |
| APP 12 — Access | DSR access endpoint | **NOT IMPLEMENTED** | ❌ MED-11 |
| APP 13 — Correction | DSR correction endpoint | **NOT IMPLEMENTED** | ❌ MED-11 |

---

## What ShopSquire Can Honestly Claim Today (March 2026)

### Genuine Differentiators — Ready to Demo

| Capability | Evidence | Demo Path |
|---|---|---|
| Bitemporal decision audit trail with hash chaining | `security/audit_chain.py` | Tamper-detect demo via `GET /api/v1/audit/verify` |
| CV return fraud detection (multi-image mismatch) | `services/cv_damage_classifier.py`, `routers/returns.py` | Submit clean laptop return with damaged-product photo |
| BEC kill chain detection (email security lab) | `security/bec_kill_chain.py`, email lab UI | Demo supplier invoice fraud with spoofed domain |
| Supply chain attack detection (typosquatting + CISA KEV) | `services/supply_chain_security.py` | `POST /api/v1/security/scan/supply-chain` with `requets` package |
| 26+ fraud signals with transparent scoring | `security/`, `services/transformer_fraud.py` | Show fraud score breakdown in decision trace |
| TLS fingerprinting (JA3/JA4) | `security/tls_fingerprint_middleware.py` | Show JA3 hash in request headers |
| Adversarial image detection (GAN, steganography) | `security/adversarial_image_detector.py`, `security/steg_detector.py` | Upload image with hidden payload |
| MITRE ATLAS + OWASP LLM Top 10 mapping | `security/atlas_map.py`, `security/framework_correlation.py` | Show attack mapping in decision trace |
| YARA-based email scanning | `security/yara_email_scan.py` | Submit email with known malicious pattern |
| Agent guardrails (prompt injection detection) | `security/agent_guardrails.py` | Submit prompt injection attempt to chat |

### Claims That Need Caveats Until Gaps Are Fixed

| Claim | Caveat | Fix Required |
|---|---|---|
| "PCI DSS compliant" | Cannot claim without QSA attestation, CSP headers, and penetration test | CRIT-07, Req 11.3 |
| "ISO 27001 certified" | Requires ISMS scope, asset inventory, and management review cadence | ISMS documentation sprint |
| "GDPR compliant" | Requires RoPA, DSR workflow, and DPAs with LLM providers | MED-03, MED-11, CRIT-10 |
| "Fully autonomous" | Defensible claim is "exception-based oversight" — autonomous within pre-approved boundaries | CRIT-05, HIGH-04 |
| "AI is auditable" | True for decision trace, but audit HMAC is hardcoded | CRIT-01 |

---

## Priority Sprint Plan

### Sprint 1 (Weeks 1–2) — Close Critical Gaps
- CRIT-01: Fix audit HMAC secret
- CRIT-02: Remove in-memory idempotency cache
- CRIT-03: Enforce connector scopes by default
- CRIT-04: Enable Celery task signing
- CRIT-05: Implement policy decision engine (`action_authority_matrix.py`)
- CRIT-06: Add PII scrubbing to DLP (`dlp_export.py`)
- CRIT-07: Add security headers middleware (`main.py`)
- CRIT-08: Add CSRF protection
- CRIT-09: Lock down metrics endpoint
- CRIT-10: Implement data residency gate

### Sprint 2 (Weeks 3–4) — Close High Gaps
- HIGH-01: Create AI model registry
- HIGH-02: Wire RBAC to route dependencies
- HIGH-03: Add LLM output filter
- HIGH-04: Implement autonomy kill switches
- HIGH-05: Write DPIA for fraud scoring
- HIGH-06: Fix CV Docker dependencies (BUG-3)
- HIGH-07: Fix email lab auth error (BUG-8)
- HIGH-08: Add ticket SLA enforcement
- HIGH-09: Add SBOM CI gate
- HIGH-10: Fix NQE context loss (BUG-1)
- IT-DET-01: Insider threat detector
- IT-DET-03: Supplier baseline drift detection
- IT-PREV-04: WORM audit log wiring

### Sprint 3 (Weeks 5–6) — Close Medium Gaps + Showcase Completion
- MED-01 through MED-12: All medium action items
- SHOWCASE-01: Audit pack download in admin UI
- SHOWCASE-02: CV fraud demo gate
- SHOWCASE-03: Supply chain scan admin widget
- SHOWCASE-04: BEC kill chain visualization
- SHOWCASE-05: Compliance heatmap dashboard
- Documentation: RoPA, DPIA, AI change management, privacy policy, framework-mapping evidence pack

---

*Companion documents:*
- [COMPLIANCE-MASTER-ACTION-PLAN.md](COMPLIANCE-MASTER-ACTION-PLAN.md)
- [COMPLIANCE-FRONTEND-HARDENING.md](COMPLIANCE-FRONTEND-HARDENING.md)
- [COMPLIANCE-INSIDER-THREAT.md](COMPLIANCE-INSIDER-THREAT.md)
