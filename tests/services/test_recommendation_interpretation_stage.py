from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.interpretation_stage import (
    resolve_interpretation_stage,
)
from src.app.services.recommendation_core.turn_router import TurnDecision


def test_resolved_product_scope_reaches_intent(monkeypatch):
    received = []
    def resolve(*args, **kwargs):
        received.append(kwargs["resolved_product_type"])
        return {"requirements": {}, "use_cases": [], "use_case_variants": {}}
    monkeypatch.setattr("src.app.services.recommendation_core.interpretation_stage.resolve_intent", resolve)
    monkeypatch.setattr("src.app.services.recommendation_core.interpretation_stage.observe_workload_interpretations",
                        lambda *args, **kwargs: None)
    for node in ("el-6-6", "el-6-2", None):
        resolve_interpretation_stage(
            TurnDecision(requested_product_node=node, node_handle=node),
            TurnEnvelope(tenant_id="default", uid="buyer", query="host software", trace_id="scope"),
            vertical="electronics", is_workload_host_product=lambda _: True,
        )
    assert received == ["el-6-6", "el-6-2", ""]


def test_accessory_keeps_buyer_requirement_but_drops_workload_floor(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.services.recommendation_core.interpretation_stage.resolve_intent",
        lambda *args, **kwargs: {
            "requirements": {"weight_kg": [("<=", 1.0)], "ram_gb": [(">=", 32.0)]},
            "use_cases": ["rendering"], "use_case_variants": {},
        },
    )
    monkeypatch.setattr(
        "src.app.services.recommendation_core.interpretation_stage.observe_workload_interpretations",
        lambda *args, **kwargs: {"status": "observed"},
    )
    result = resolve_interpretation_stage(
        TurnDecision(
            requirements={"weight_kg": [("<=", 1.0)]}, use_cases=("rendering",),
            requested_product_node="accessory-bag",
        ),
        TurnEnvelope(
            tenant_id="default", uid="buyer", query="a light bag for rendering",
            trace_id="trace-1",
        ),
        vertical="Accessories", is_workload_host_product=lambda _node: False,
    )

    assert result.decision.requirements == {"weight_kg": [("<=", 1.0)]}
    assert result.dropped_requirement_keys == ("ram_gb",)
    assert result.shadow == {"status": "observed"}
