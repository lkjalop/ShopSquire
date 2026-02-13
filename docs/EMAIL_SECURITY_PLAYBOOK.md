# Email Security Playbook (BEC/Phishing/Ransomware)

## Detection
- Indicators: risky keywords (urgent, wire transfer), domain lookalikes, reply-to mismatches, DMARC fail rates.
- Sources: DMARC aggregate reports, inbound email metadata, security observer signals.

## Immediate Actions
- Warn: notify admin and relevant stakeholders with sanitized event details.
- Sandbox: isolate suspicious attachments/links; fetch in a sandboxed environment (no execution in production environment).
- Ticket: auto-create a high-severity ticket when indicators exceed thresholds.

## Escalation
- Criteria: multiple high-risk indicators, DMARC fail rate > 50%, known IoCs.
- Steps: lock affected accounts, enable MFA challenges for admin, quarantine related sessions, suspend risky automations.

## Investigation
- Collect: sanitized email headers/metadata, DMARC summary, logs for related activities.
- Analyze: correlate with decision traces and IAM `iam_activity` events to determine scope.
- Report: use the template to document findings, timeline, and impacted systems.

## Post-Attack
- Root cause analysis, credential rotation, update policies and detectors.
- Add IoC tags via `src/app/observability/ioc.py` and update deny-lists.
- Monitor: increase alerting sensitivity temporarily; audit admin actions.

## Agent Boundaries
- Allowed: emit telemetry, create tickets, quarantine sandbox, request human approval for destructive actions.
- Not Allowed: execute attachments/binaries, exfiltrate data, disable core protections, change RBAC policies without approval.

## Zero Trust Measures
- Enforce RBAC + MFA for admin routes; `AdminMfaMiddleware` enabled.
- Hash identifiers and redact sensitive content before external emission.
- Least privilege for connectors; env-gated sinks.
- Continuous IAM telemetry (`iam_activity`) for authn/authz outcomes.
