# ShopSquire Security Architecture — Controls, Taxonomies, Compliance Mapping

Version: 2.0 (2026‑01‑19)

## 1) Security Model (At a Glance)
- Zero‑Trust Agents: propose‑only; no direct write scopes.
- Security Observer (sidecar/logical): watches all tool calls, enforces input/output hygiene, computes composite risk, and emits audit artifacts.
- Transaction Firewall: ABAC policies, idempotency, rate‑limit/circuit breakers, approval tiers.
- Evidence & Provenance: bi‑temporal decision logs with retrieved_context, policy_version, dependency_status, confidence, and scoring_config snapshot.

## 2) Threat Frameworks in Scope
- MITRE ATLAS (ML‑specific threats) — baseline techniques covered:
  - AML.T0043 Craft Adversarial Data (Prompt Injection/Jailbreak)
  - AML.T0020 Supply Chain Compromise (Tampered responses/SDK)
  - AML.T0048 Exfiltration via Inference (PII/Secrets leakage)
  - AML.T0015 Model Evasion/Obfuscation (Unicode/Homoglyph)
- OWASP LLM Top 10 & OWASP API Top 10 — mapped in section 4.
- STRIDE categories — mapped to detections/controls.
- DREAD & CVSSv3 — normalized severity scoring.
- KEV (Known Exploited Vulnerabilities) — threat intelligence overlay.

## 3) Composite Risk Scoring (Observer)
Inputs
- Technique signals (MITRE ATLAS)
- STRIDE category flags
- DREAD component scores (0–10 each, weightable per org)
- CVSS base score (if relevant to dependency vulns)
- KEV presence (boolean + recency weighting)
- Context multipliers (tenant sensitivity, data class)

Computation (example defaults)
- risk_raw = w_mitre*mitre_sev + w_stride*stride_sum + w_dread*avg(D,R,E,A,D) + w_cvss*f(cvss) + w_kev*kev_weight
- risk_adj = risk_raw * context_multiplier (e.g., PII present → 1.5x)
- Verdict bands: info <20, warn 20–49, high 50–79, critical ≥80
- All weights are configurable in config/security/taxonomy/risk_correlation_policy.json

Actions
- info/warn: log + dashboard
- high: block LLM or require human review (depending on path)
- critical: kill‑switch trigger and escalation

## 4) OWASP Coverage Matrix (Selected)
- LLM01 Prompt Injection → Regex/semantic guards, Unicode NFKC, tool‑whitelist, system prompt redaction, policy gates
- LLM02 Insecure Output Handling → PII scrubbing/masking, allowlist formatters
- LLM03 Training Data Poisoning → Trusted models only (no per‑user fine‑tune in MVP), SBOM/attestation
- LLM06 Sensitive Information Disclosure → Response guards; redact secrets; provenance required for factual claims
- LLM08 Excessive Agency → Propose‑only agents; Firewall executes
- API01 BOLA → Ownership checks in Firewall/routers; 403/404 hardening
- API04 Rate Limiting → Per‑tenant limits at CRAG gateway

## 5) Controls by Layer
- Input Hygiene: Unicode normalize, token budget check, regex templates for jailbreak patterns, rate limiting
- Retrieval Discipline: Forced retrieval for volatile claims; CacheRAG caches source objects, not generated text
- Output Hygiene: PII detector, JSON schema validation, safety templates
- Policy Gating: ABAC rules (caps, approvals), idempotency, circuit breakers
- Observability: Decision/Evidence/Policy/Health appended to bi‑temporal logs; OpenTelemetry spans (optional)

## 6) Compliance Cross‑Mapping
- ISO 42001
  - 5.2 AI Policy → policy engine + documented rules
  - 7.5 Documented Info → decision logs (bi‑temporal)
  - 8.3 Design & Development → Observer validation; change control via flags
  - 9.1 Monitoring & Measurement → factor telemetry, RAGAS, KPIs
  - 10.2 Nonconformity & Corrective → degradation tiers, rollback
- NIST AI RMF
  - GOVERN 1.2 Record‑keeping → decision logs, security events
  - MAP 1.1 Context & Impact → PRD risk register; threat models
  - MEASURE 2.3 Performance → RAGAS, latency, error/override rates
  - MANAGE 1.1 Incident Response → alerts, kill‑switch, playbooks
- EU AI Act (Article 17 focus)
  - Automated logging of events/decisions → decision_logs
  - Human oversight for high‑risk decisions → approval tiers
  - Traceability/Explainability → retrieved_context, policy_version, confidence

## 7) Data Retention & Privacy
- Logs: hot 7d (PostgreSQL), warm 90d (OLAP), cold ≥7y (archive)
- PII never in logs (customer_id only); Observer masks output
- Right‑to‑delete: cascade by customer_id (demo note)

## 8) Configuration Artifacts (this repo)
- config/security/taxonomy/mitre_atlas_techniques.json (subset + refs)
- config/security/taxonomy/dread_weights.json
- config/security/taxonomy/cvss_v3_severity_map.json
- config/security/taxonomy/stride_categories.json
- config/security/taxonomy/kev_feed_source.json (CISA feed pointer)
- config/security/taxonomy/risk_correlation_policy.json (weights/bands)

## 9) Operating Procedures
- Daily: review high/critical events, random sample of auto‑approved actions
- Weekly: analyze overrides; update policies/weights; RAGAS trend
- Monthly: audit export, drills for kill‑switch/degradation

## 10) Validation Scenarios (must pass)
- Prompt Injection blocked (high)
- Unicode homoglyph attack normalized then blocked
- PII disclosure masked
- Excessive discount blocked by caps; >$ threshold queued
- Ownership enforcement on order access (BOLA)
- Rollback restores legacy paths under <5 min
