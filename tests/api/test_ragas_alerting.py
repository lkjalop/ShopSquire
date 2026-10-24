from tests.api.test_ragas_baseline import evaluation_db, seed_measurement, approve_baseline
from src.app.services.ragas_eval import ci_guard_check


def test_ragas_ci_guard_detects_drop_with_reviewed_baseline(evaluation_db):
    metadata = seed_measurement(evaluation_db, score=.4)
    approve_baseline(evaluation_db, metadata)
    out = ci_guard_check(window=40, drop_pct=.1)
    assert out['ok'] is False
    assert out['reason'] == 'moving_avg_drop'
