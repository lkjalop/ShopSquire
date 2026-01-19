from src.app.analytics.anomaly import ewma, is_anomaly


def test_ewma_basic():
    s = [1, 1, 1, 1, 1]
    assert abs(ewma(s, 0.2) - 1.0) < 1e-6


def test_is_anomaly():
    s = [1, 1, 1, 1, 1]
    assert is_anomaly(2.0, s, 0.2, 3.0) is True
    assert is_anomaly(1.05, s, 0.2, 3.0) is False
