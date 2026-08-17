from types import SimpleNamespace

from src.app.services.recommendation_core.typed_stage_coordinator import (
    CoordinatedStage,
    RecommendationPhase,
    run_coordinated_stages,
)
import pytest


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


def test_coordinator_rejects_phase_regression_before_side_effects():
    response = Response()
    effects = []

    with pytest.raises(ValueError, match="recommendation_stage_order_invalid"):
        run_coordinated_stages(response, (
            CoordinatedStage(
                RecommendationPhase.COMMERCIAL, "commercial",
                lambda: effects.append("commercial"),
            ),
            CoordinatedStage(
                RecommendationPhase.EVIDENCE, "evidence",
                lambda: effects.append("evidence"),
            ),
        ))

    assert effects == []
    assert response.recorded == []


def test_stage_emits_artifact_lineage_instead_of_reconstructing_it_later():
    response = Response()
    run_coordinated_stages(response, (
        CoordinatedStage(
            RecommendationPhase.FIT, "fit", lambda: None,
            stage_id="fit-exact", input_artifact_refs=("requirements:accepted",),
            output_artifact_refs=("fit:verdicts",),
            dependency_stage_ids=("evidence-accepted",),
        ),
    ))
    values = response.recorded[0][1]
    assert values["stage_id"] == "fit-exact"
    assert values["input_artifact_refs"] == ("requirements:accepted",)
    assert values["output_artifact_refs"] == ("fit:verdicts",)
    assert values["dependency_stage_ids"] == ("evidence-accepted",)
