# Capability Contracts

This document defines inputs, outputs, and policy hooks for core capabilities: pricing, recommend, support, and security. Contracts are versioned. All payloads are JSON.

## Pricing (v1)
- Inputs: { uid: string, cart_total_cents: int, sku?: string, idempotency_key?: string }
- Outputs: { eligible: bool, proposal: { cart_total_cents: int, discount_percent: int, reason: string }, firewall: { allowed: bool, approval_required: bool, reason: string }, executed: bool, degraded: bool }
- Policy Hooks:
  - pre: `firewall.check_pricing(cart_total_cents, proposed_discount_percent)`
  - post: decision logging with `policy_version`; approval required routing
  - safety: rate-limit, token budgets, circuit breaker; degraded rules fallback

## Recommend (v1)
- Inputs: { uid: string, query: string, constraints?: { brands?: string[], specs?: string[], budget_max?: int } }
- Outputs: { ranked_skus: string[], rationale: string, confidence: number }
- Policy Hooks:
  - pre: input sanitization/redaction; security analysis
  - post: proposal validation (no out-of-catalog SKUs), decision logging
  - safety: anomaly detection, degraded heuristic reranker

## Support (v1)
- Inputs: { uid: string, question: string, context?: object }
- Outputs: { answer: string, citations?: string[], escalation_required?: bool }
- Policy Hooks:
  - pre: prompt filtering, PII redaction
  - post: hallucination guard, citation minimums, escalation on low confidence
  - safety: rate-limit, token budgets, kill switch

## Security (v1)
- Inputs: { path: string, payload: object, analysis?: object }
- Outputs: { severity: 'info'|'low'|'medium'|'high'|'critical', verdict_score: int }
- Policy Hooks:
  - pre: input scoring (MITRE/OWASP), risk correlation policy
  - post: event persistence, escalation/block workflows
  - safety: SIEM export, webhook dispatch via outbox

## Contract Versioning
- `policy_version` and capability version must be stored with the decision.
- Backwards compatibility through additive fields; breaking changes require new version and migration notes.
