from src.app.services.discovery_engine_reliability import DiscoveryEngineReliability


def test_engine_failures_are_rolled_up_and_only_unhealthy_engine_is_suppressed():
    health = DiscoveryEngineReliability(window_size=5, minimum_attempts=3)
    for _ in range(3):
        health.record(
            endpoint="search.local",
            receipt={
                "engines_queried": ["bing", "google", "wikipedia"],
                "engines_responded": ["bing", "google"],
                "engine_failures": [{"engine": "wikipedia", "reason": "timeout"}],
            },
            latency_ms=120,
        )

    rows = {row["engine"]: row for row in health.snapshots("search.local")}
    assert rows["bing"]["responses"] == 3
    assert rows["bing"]["average_latency_ms"] == 120
    assert rows["wikipedia"]["failures"] == 3
    assert rows["wikipedia"]["suppressed"] is True
    assert health.recommended_engines("search.local") == ["bing", "google"]


def test_reliability_never_disables_the_only_known_engine():
    health = DiscoveryEngineReliability(minimum_attempts=2)
    for _ in range(2):
        health.record(
            endpoint="search.local",
            receipt={
                "engines_queried": ["only"],
                "engines_responded": [],
                "engine_failures": [{"engine": "only", "reason": "timeout"}],
            },
            latency_ms=20,
        )

    assert health.recommended_engines("search.local") == ["only"]
