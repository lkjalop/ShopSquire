# Thinking Modes Runbook

Date: Jan 2026

## Overview

Tiered thinking routes requests across three levels:
- Tier 0: Deterministic rules, cached responses, formatting, and lookups. No LLM.
- Tier 1: Preserved thinking (single-pass rerank/summarize/parse), max one tool call.
- Tier 2: Interleaved thinking for complex multi-turn or higher risk/amount; bounded to 2–4 tool calls with allowlists.

## Routing Triggers
- risk_adj ≥ 0.5
- amount ≥ $250
- intent_confidence < 0.7
- multi_turn = True
- complexity keywords: compare, versus, tradeoff, analyze, explain why, best option, recommend

## Agent Application
- Orchestrator: 0 for clear, low-value carts; 1 for quick rerank; 2 for multi-turn/conflicting/high risk.
- InventoryAgent: 0 deterministic stock rules; 1 summarize alternatives/restock; 2 discrepancies/VIP/B2B/recall → human.
- Fraud Scorer/CV: 0–2 rules/stats; 3–4 ML/VLM only when high-value or low-confidence.
- Support: 0 known intents; 1 summarize KB; 2 safety/complex complaints → ticket/handoff.

## Escalation Rules
- Trigger on conflicting signals, stock discrepancy, recall, repeated claims, CV anomalies.
- Actions: create ticket (IncidentRoute), assign role (owner/merchant/support), collect structured details.

## Guardrails
- Prefer cache/rule paths first.
- Hard cap tool/LLM calls per tier; log usage and confidence.
- Redact outputs, sanitize inputs. Isolate tenant context via tenant_id in decisions and cache keys.

## Configuration Flags
- MODEL_T1, MODEL_T2, MODEL_T3: model names per tier.
- DECISION_LOG_WRITES_ENABLED: enable decision persistence.
- POLICY_VERSION: version string for policy metadata.
- RAGAS_EVAL_ENABLED: enable evaluation pipeline.

## Endpoints
- GET /api/v1/trace/{id}/events: raw events.
- GET /api/v1/trace/{id}/timeline: summary + timeline for UI.

## Troubleshooting
- Decision logs missing tenant_id → ensure schema has tenant_id and app version includes tenant fix.
- High token usage → verify TierRouter decisions, cache hit rate, and tool budgets.
- Timeline empty → confirm trace_id passed on events and DB availability.

