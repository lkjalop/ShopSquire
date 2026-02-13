# Runbook: ControlFailuresSpiking

Alert: Compliance control failures > 10 in 10 minutes

Steps:
- Identify failing controls via metrics; map to business impact
- Review recent agent outputs flagged by `observer` for PII/PCI/jailbreak
- Tighten guardrails or switch to rule-based responses for affected flows
- Notify compliance; open ticket and document incidents
- Conduct data redaction sweep and verify logs are compliant
