from src.app.services.decision_bundle import write_immutable_decision_bundle


def test_decision_bundle_includes_model_pinning_fields():
    out = write_immutable_decision_bundle(
        trace_id="t-1",
        actor_type="agent",
        actor_id="ml_gate",
        tenant_id="tenant-a",
        resource_id="res-1",
        action="risk_gate",
        policy_version="v3",
        decision="allow",
        model_inputs={"score": 0.2},
        model_card={"name": "gbm-risk-gate", "owner": "mlops"},
        model_version="gbm_20260227",
    )
    payload = out.get("payload") or {}
    assert str(payload.get("model_version") or "") == "gbm_20260227"
    assert (payload.get("model_card") or {}).get("name") == "gbm-risk-gate"

