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


def test_recent_engine_health_survives_process_reconstruction(tmp_path):
    database = tmp_path / "discovery-health.db"
    first = DiscoveryEngineReliability(
        window_size=3, minimum_attempts=2, storage_path=str(database),
    )
    for _ in range(3):
        first.record(
            endpoint="search.local",
            receipt={
                "engines_queried": ["bing", "wikipedia"],
                "engines_responded": ["bing"],
                "engine_failures": [{"engine": "wikipedia", "reason": "timeout"}],
            },
            latency_ms=80,
        )

    restored = DiscoveryEngineReliability(
        window_size=3, minimum_attempts=2, storage_path=str(database),
    )
    rows = {row["engine"]: row for row in restored.snapshots("search.local")}
    assert rows["bing"]["responses"] == 3
    assert rows["wikipedia"]["failures"] == 3
    assert rows["wikipedia"]["suppressed"] is True
    assert restored.recommended_engines("search.local") == ["bing"]


def test_persistence_failure_never_breaks_research_telemetry(tmp_path):
    directory_instead_of_database = tmp_path / "not-a-database"
    directory_instead_of_database.mkdir()
    health = DiscoveryEngineReliability(storage_path=str(directory_instead_of_database))

    health.record(
        endpoint="search.local",
        receipt={"engines_queried": ["bing"], "engines_responded": ["bing"]},
        latency_ms=12,
    )

    assert health.snapshots("search.local")[0]["responses"] == 1
