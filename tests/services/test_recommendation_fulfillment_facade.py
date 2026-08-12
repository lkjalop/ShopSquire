from src.app.services.recommendation_fulfillment_facade import (
    RecommendationFulfillmentRequest,
    project_recommendation_fulfillment,
)


def test_facade_forces_deferred_read_only_projection(monkeypatch):
    observed = {}

    def fake_stage(**kwargs):
        observed.update(kwargs)
        kwargs["payload"].update({
            "availability": {"shortfall": 18},
            "fulfillment_options": [{"type": "split"}],
            "sourcing_intent": {"mode": "deferred_to_cart"},
        })
        return "12 now and 18 require sourcing."

    monkeypatch.setattr("src.app.services.recommend_fulfillment_stage.run_fulfillment_stage", fake_stage)
    result = project_recommendation_fulfillment(RecommendationFulfillmentRequest(
        results=[{"sku": "A"}], constraints={"order_quantity": 30}, uid="buyer",
        trace_id="trace", tenant_id="tenant", query="30 laptops", flags={"FULFILLMENT_CASES_ENABLED": True},
    ))

    assert observed["flags"]["FULFILLMENT_DEFER_TO_CART"] is True
    assert observed["allow_query_order_split"] is False
    assert result.availability == {"shortfall": 18}
    assert result.sourcing_intent == {"mode": "deferred_to_cart"}
    assert result.summary == "12 now and 18 require sourcing."
