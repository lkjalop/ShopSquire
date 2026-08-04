from __future__ import annotations

from src.app.services import db_read_routing


def test_unknown_replica_lag_falls_back_to_primary(monkeypatch) -> None:
    primary = object()
    replica = object()
    monkeypatch.setenv("READ_REPLICA_URL", "postgresql://replica/db")
    monkeypatch.setattr(db_read_routing, "get_engine", lambda: primary)
    monkeypatch.setattr(db_read_routing, "_get_read_engine", lambda: replica)
    monkeypatch.setattr(db_read_routing, "replica_lag_seconds", lambda: None)

    assert db_read_routing.choose_read_engine() is primary


def test_healthy_replica_is_selected_within_lag_budget(monkeypatch) -> None:
    primary = object()
    replica = object()
    monkeypatch.setenv("READ_REPLICA_URL", "postgresql://replica/db")
    monkeypatch.setenv("READ_REPLICA_MAX_LAG_SECONDS", "2")
    monkeypatch.setattr(db_read_routing, "get_engine", lambda: primary)
    monkeypatch.setattr(db_read_routing, "_get_read_engine", lambda: replica)
    monkeypatch.setattr(db_read_routing, "replica_lag_seconds", lambda: 1.0)

    assert db_read_routing.choose_read_engine() is replica


def test_strong_reads_never_use_replica(monkeypatch) -> None:
    primary = object()
    monkeypatch.setattr(db_read_routing, "get_engine", lambda: primary)
    monkeypatch.setattr(
        db_read_routing,
        "_get_read_engine",
        lambda: (_ for _ in ()).throw(AssertionError("replica consulted")),
    )

    assert db_read_routing.choose_read_engine("strong") is primary
