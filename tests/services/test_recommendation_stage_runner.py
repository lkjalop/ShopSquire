import pytest

from src.app.services.recommendation_core.cancellation import (
    RecommendationCancellation, RecommendationCancelled,
)
from src.app.services.recommendation_core.stage_runner import run_guarded_stage


class Response:
    def __init__(self):
        self._msg_priority = 0
        self.rows = []

    def record_stage(self, name, **values):
        self.rows.append((name, values))


def test_stage_failure_is_recorded_without_escaping():
    response = Response()
    run_guarded_stage(response, "fit", lambda: (_ for _ in ()).throw(ValueError("bad evidence")))
    assert response.rows[0][0] == "fit"
    assert response.rows[0][1]["status"] == "error"


def test_cancellation_is_never_swallowed():
    response = Response()
    cancellation = RecommendationCancellation.with_timeout(60)
    cancellation.cancel("buyer_disconnected")
    with pytest.raises(RecommendationCancelled):
        run_guarded_stage(response, "evidence", lambda: None, cancellation=cancellation)
