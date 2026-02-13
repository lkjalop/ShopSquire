# ShopSquire Security Demo — Short Deck (8 slides)

## 1. Title
- I built an agentic AI security platform. Here’s what I learned.
- Agents triage in seconds. Humans decide what matters.

## 2. The 3 Threat Lanes
- Prompt Injection (NLP + CV): hidden instructions, metadata poisoning, authority impersonation
- Email BEC / Phishing / Ransomware
- Supply‑Chain Risk (3rd‑party connectors, schema drift, replay)

## 3. How ShopSquire Stops It
- Sanitize → Classify → Policy Gate (deny/redact/flag)
- Authentication Wall + ML Fraud Signals + Quarantine/Step‑Up Approval
- OAuth2 + Least Privilege + Runtime Anomaly Detection + Auto‑Quarantine

## 4. Architecture Principles
- Deterministic rules first; LLM only for judgment calls
- Interleaved thinking to avoid context rot
- Parallel agent swarm: specialized, concurrent detectors

## 5. Evidence & Compliance
- WORM audit trail · HMAC signed webhooks · bi‑temporal decision log
- ISO 42001 · NIST AI RMF (MAP‑MEASURE‑MANAGE‑GOVERN) · OWASP (API · Agentic AI · LLM)

## 6. Live Demo (3 lanes)
- Prompt Injection: strip hidden commands → score → DENY/redact → dashboard event
- Email BEC/Ransomware: spoofed invoice → auth fail → quarantine + IOC bundle
- Supply‑Chain: schema drift + XSS/eval → auto‑quarantine per tenant

## 7. Business Outcomes
- Reduced financial loss (BEC blocked pre‑inbox)
- Per‑tenant containment (no lateral movement)
- Audit‑ready evidence (faster audits; fewer disputes)
- Operational efficiency (agents triage; humans approve what matters)

## 8. Call to Action
- Internal review first → publish highlights externally
- Ask: connect with security leaders; collaborate; feedback on controls
