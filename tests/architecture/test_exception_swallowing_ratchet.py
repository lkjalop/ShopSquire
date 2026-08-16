from scripts.check_exception_swallowing import evaluate_exception_debt


def test_high_risk_exception_swallowing_can_only_shrink():
    assert evaluate_exception_debt() == []
