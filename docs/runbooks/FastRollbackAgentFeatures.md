# Fast Rollback: Agent Feature Toggles

## Purpose
Rapid rollback procedure for context-injection and graph-enrichment features when SLO or quality alerts fire.

> NOTE (2026-06-30): The `DYNAMIC_CONTEXT_PROVIDER_ENABLED` / `CAG_CONTEXT_ENABLED` /
> `GRAPH_RAG_ENABLED` toggles previously listed here were dead config — defined in
> `config.py` but never read in `src/app`. They were removed. This runbook is
> retained as a template for future context/graph rollouts; replace the toggle
> names below when those features ship a real implementation + flag.

## Trigger Conditions
- `ABVariantBQualityDrop`
- `ABVariantBQualityCritical`
- `AgentFeatureToggleUsageDrop`
- Any severe latency/error SLO breach linked to recent rollout

## Immediate Actions (under 5 minutes)
1. Set all rollout toggles off via environment variables (replace `<TOGGLE_NAME>` with the live flag(s)):
   - `<TOGGLE_NAME>=0`
2. Keep service running and confirm health:
   - `GET /healthz` returns `200`
3. Confirm impact stabilization:
   - Error rate normalizes
   - P95 latency trends down
   - Escalation rate returns to baseline

## API-Based Rollback (alternative)
1. Call `POST /api/v1/admin/flags` as owner and update:
   - `<TOGGLE_NAME>=false`
2. Verify with `GET /api/v1/admin/diagnostics/agent-toggles`.

## Verification Checklist
1. `GET /api/v1/admin/diagnostics/agent-toggles`
2. `GET /metrics` and inspect:
   - `shopsquire_ab_decision_quality_avg{variant="A"|"B"}`
   - `shopsquire_agent_feature_toggle_used_total`
3. Confirm no critical quality regression remains.

## Gradual Re-enable Plan
1. Enable one toggle at a time in staging.
2. Canary 5-10% traffic.
3. Observe for 30 minutes before next toggle.
4. Promote to production only after stable quality and SLOs.
