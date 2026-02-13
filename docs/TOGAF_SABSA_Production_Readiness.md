# ShopSquire Production Readiness: TOGAF + SABSA Deep Dive

## Executive Summary

This document maps ShopSquire’s path to production readiness using TOGAF (architecture/operating model) and SABSA (security architecture), with a prioritized, actionable checklist. Focus is on marketplace operations (buyers, suppliers), data handling (PII, orders), and email correspondence (transactional, supplier, marketing). Outcomes target reliability, security, compliance, and operability within 4–8 weeks.

Top priorities (P0):
- Architecture governance + environments: Define prod/non-prod, change gates, config isolation.
- Identity & access: Central RBAC for staff, suppliers, and service accounts; MFA; least privilege.
- Data protection: Classification, encryption at rest/in-transit, key management, backups, DR.
- Email deliverability & compliance: SPF/DKIM/DMARC, transactional vs marketing separation, consent.
- Observability & incident response: Logs, metrics, traces, alerting, on-call runbooks, retention.
- Privacy & compliance: GDPR/CCPA policies, DSR process, audit trails, vendor management.

## TOGAF Considerations (Production Readiness)

### Architecture Vision → Business Architecture
- Business capabilities: Marketplace onboarding, catalog ingestion, search/recommendations, checkout, supplier settlement, support.
- KPIs: Conversion rate, order success rate, SLA for supplier updates, email delivery rate, MTTR.
- Target outcomes: Secure, reliable buyer/supplier flows; regulated data handling; provable compliance.

### Information Systems Architecture
- Application services: API gateway, catalog/ERP connectors, recommendation service, email service, telemetry.
- Data architecture: PII registry, product catalogs, orders, events; lineage and retention per domain.
- Integration: Webhooks (Shopify), HEC/Splunk, email providers (Postmark/SendGrid), payment gateways.

### Technology Architecture
- Environments: Dev, Staging, Prod with isolated configs and secrets.
- Networking/edge: WAF, rate limiting, TLS enforcement; service discovery.
- Storage: Managed DB with backups; object storage for media; key vault for secrets.

### Opportunities & Solutions → Migration Planning
- Quick wins: Email auth (SPF/DKIM/DMARC), RBAC, log aggregation, PII classification.
- Work packages: Data protection program, incident response, supplier onboarding flows, catalog normalization.
- Dependencies: Identity provider, email provider, logging/metrics stack, secrets management.

### Implementation Governance
- Change gates: Architecture Decision Records (ADR), security review checklist, automated tests in CI.
- Config management: Feature flags, PYTHONPATH/runtime isolation, env var contracts documented.
- DR drills: Quarterly restore test, failover runbooks, RTO/RPO defined.

### Architecture Governance
- Boards: Architecture, Security, Data Governance, and Change Advisory Board (lightweight).
- Policies: Data minimization, access reviews, vendor DPAs, vulnerability mgmt (SAST/DAST/Dep scans).

## SABSA Considerations (Security Architecture)

### Contextual Layer (Business View)
- Business attributes: Trust, privacy, safety, uptime, integrity of orders, non-repudiation of supplier changes.
- Risk drivers: PII leakage, payment fraud, supplier impersonation, email spoofing, data loss.

### Conceptual Layer (Security Concepts)
- Trust zones: Public web, supplier portal, back-office, CI/CD, data plane.
- Identities: Buyers, suppliers, staff, services; strong auth and authorization.
- Security services: Authentication, authorization (RBAC/ABAC), encryption, logging, monitoring, IR.

### Logical Layer (Design)
- Controls: MFA, role-based access; TLS 1.2+; KMS-managed keys; audit logging; email auth; WAF.
- Data controls: Classification (Public/Confidential/Sensitive); retention; pseudonymization where feasible.
- Monitoring: Central logs (Splunk/ELK), metrics (Prometheus), traces; anomaly detections for email and orders.

### Physical Layer (Implementation)
- Components: IdP (Auth0/Entra/Keycloak), Email (Postmark/SendGrid), Secrets (Azure Key Vault/AWS KMS), DB backups.
- Network: WAF/CDN, firewall rules, rate limiting; DMARC and MTA-STS for email.
- Hardening: CIS baselines, dependency scanning, container image signing.

### Component Layer (Operations)
- Procedures: On-call, IR playbooks, access reviews, quarterly DR; supplier verification workflow.
- Evidence: Audit logs for DSRs, email consent and unsubscribe events, supplier change approvals.

## Prioritized Production Checklist

P0 – Critical (Weeks 1–2)
1. Identity & Access: Centralize auth; enforce MFA and RBAC for staff/suppliers; service principals with least privilege.
2. Email Authentication & Separation: Configure SPF/DKIM/DMARC; separate transactional vs marketing domains; unsubscribe and consent flows.
3. Data Classification & Protection: Classify PII; encrypt at rest/in-transit; key rotation; backups + tested restores; retention policies.
4. Observability Baseline: Centralized logs/metrics/traces; error budgets and SLOs; alerting; correlation IDs.
5. Privacy & Compliance: GDPR/CCPA notices; DSR process; vendor DPAs; audit trail for email and supplier changes.

P1 – High (Weeks 2–4)
6. Secure SDLC: CI unit/integration tests; SAST/dep scanning; secrets scanning; pre-prod security checks.
7. Edge Security: WAF, rate limiting, bot protection; strict TLS; HSTS; secure cookies.
8. Incident Readiness: IR playbooks, comms plan, tabletop exercise; log immutability.
9. Supplier Onboarding & Verification: KYC/KYB checks; verified email domains; approval workflows.
10. Data Quality & Lineage: Catalog lineage; validation; schema versioning; migration runbooks.

P2 – Medium (Weeks 4–8)
11. Business Continuity: RTO/RPO formalization; DR runbooks; chaos drills.
12. Cost & Performance: Capacity planning; backpressure controls; autoscaling; caching; CDN for static assets.
13. Authorization Depth: Attribute-based policies for sensitive endpoints; scoped tokens; fine-grained supplier permissions.
14. Advanced Monitoring: Fraud heuristics for orders/email; anomaly alerts; domain reputation monitoring.

## Data Handling (Buyers, Suppliers, Orders)

### Data Classification
- Categories: Identity (name, email), Profile (preferences), Order (history, addresses), Supplier (legal entity data), Telemetry.
- Levels: Public, Internal, Confidential, Sensitive (PII/payment). Map fields explicitly.

### Lawful Basis & Minimization
- Lawful basis: Contract (orders, supplier), Consent (marketing), Legitimate interest (security telemetry).
- Minimize collection and retention; avoid storing unnecessary PII in logs/emails.

### Protection & Key Management
- Encryption: TLS for transit; DB/storage encryption; field-level for Sensitive data where needed.
- Keys: Managed KMS; rotation every 6–12 months; access via workload identities; audit key access.

### Access Control & Auditing
- RBAC/ABAC for staff and suppliers; break-glass accounts; quarterly reviews.
- Audit trails: DSRs, supplier profile edits, order changes, consent/unsubscribe events.

### Retention & DSRs
- Retention: Orders per legal requirements; marketing data per consent; telemetry 30–90 days.
- DSRs: Discover, export, delete; verify identity; log fulfillment steps.

### Backups & DR
- Backups daily; point-in-time recovery; encryption; quarterly restore test.

## Email Correspondence (Users, Buyers, Suppliers)

### Categories
- Transactional: Signup, verification, order confirmation, shipping updates, password reset.
- Supplier: Onboarding, catalog updates, settlement notices, compliance requests.
- Marketing: Newsletters, promotions (opt-in only, separate domain/subdomain).

### Deliverability & Authentication
- DNS: SPF (include provider), DKIM keys, DMARC (p=quarantine or reject for marketing), MTA-STS.
- Separation: Use `mail.shopSquire.com` (transactional) and `news.shopSquire.com` (marketing) to isolate reputation.

### Architecture
- Email service abstraction with provider adapters (Postmark/SendGrid).
- Event-driven triggers: Order events, supplier workflow steps; enqueue and retry with exponential backoff.
- Templates: Localized, versioned templates; content security (no sensitive data); link tracking with consent.
- Monitoring: Bounce/complaint webhooks; rate limits; dashboards; alert on spikes.
- Compliance: Unsubscribe headers; consent records; footer details (address, contact); CAN-SPAM/GDPR alignment.

### Operations
- Runbooks: Bounce handling, complaint investigation, domain reputation recovery, template rollout.
- Audit logs: Who sent what, when, to whom; correlate with order or supplier events.

## Quick Wins (Implementation Guide)

1. Configure DNS for email: SPF/DKIM/DMARC; distinct domains for transactional/marketing.
2. Centralize identities: Choose IdP; enable MFA; set up RBAC roles for staff/suppliers.
3. Add PII registry: Document field-level classification; update logging to redact PII.
4. Observability: Ensure log/trace correlation IDs; set error-rate alerts; ship logs to Splunk/ELK.
5. Backups: Enable automated DB backups; document RTO/RPO; run a restore test.
6. Policies: Publish privacy notice and DSR SOP; vendor DPA review for email provider and telemetry.

## Governance Artifacts

- Architecture Decision Records (ADR) for IdP, email provider, KMS, logging stack.
- Security checklist for releases (secrets, scans, tests, change approvals).
- Data retention schedule and DSR SOP.
- Incident response playbooks.

## Next Steps

- Approve providers (IdP, email); implement DNS/auth.
- Establish environments and secrets management.
- Roll out RBAC and PII safeguards.
- Schedule DR and IR drills.
