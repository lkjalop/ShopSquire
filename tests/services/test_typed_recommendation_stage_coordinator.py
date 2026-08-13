from types import SimpleNamespace

from src.app.services.recommendation_core.typed_stage_coordinator import (
    CoordinatedStage,
    RecommendationPhase,
    run_coordinated_stages,
)


class Response:
    def __init__(self):
        self._msg_priority = 0
        self.recorded = []

    def record_stage(self, name, **values):
        self.recorded.append((name, values))


def test_coordinator_preserves_order_and_failure_isolation():
    response = Response()
    effects = []

    def fail():
        raise RuntimeError("optional stage failed")

    run_coordinated_stages(response, (
        CoordinatedStage(RecommendationPhase.FIT, "fit", lambda: effects.append("fit")),
        CoordinatedStage(RecommendationPhase.COMMERCIAL, "commercial", fail),
        CoordinatedStage(RecommendationPhase.RESPONSE, "response", lambda: effects.append("response")),
    ), cancellation=SimpleNamespace(raise_if_cancelled=lambda: None))

    assert effects == ["fit", "response"]
    assert [item[0] for item in response.recorded] == ["fit", "commercial", "response"]
    assert [item[1]["status"] for item in response.recorded] == ["ok", "error", "ok"]
