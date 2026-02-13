# NLP Quality Gate Runbook

Purpose: Monitor and respond to shifts in NLP contract analysis quality.

- Signals: Contract NLP `score`, `risks`, and gate decision (`allow`, `review`, `abstain`).
- Thresholds:
  - min_score: 0.6 (review below), abstain_below: 0.4
  - precision_target: 0.85, recall_target: 0.80
- Actions:
  - Review Spike: If `review`/`abstain` decisions exceed baseline by >2x over 15m, sample decisions, validate inputs, and check feature flags in `config/feature_flags.json`.
  - LLM Drift: If mode changes to `deterministic+llm` frequently, validate LLM endpoint health and latency.
  - Risk Weighting: Adjust `CONTRACT_NLP_QUALITY.risk_weights` for false positives/negatives.

Checklist:
- Verify backend emits `contract_nlp_analysis` and `nlp_quality_gate` trace events.
- Confirm dashboards show gate decisions over time.
- Validate downstream routing changes (security_review escalation rate) for regressions.

Rollback:
- Set `CONTRACT_NLP_ASSIST_ENABLED` to false to disable assist.
- Raise `abstain_below` temporarily to reduce auto-escalations.
