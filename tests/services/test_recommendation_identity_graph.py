from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.recommendation_identity_graph import (
    ensure_identity_graph_tables,
    register_identity_observations,
    linked_uid_hashes,
)


def test_identity_graph_links_cross_session_by_device():
    with db_session() as db:
        ensure_identity_graph_tables(db)
        register_identity_observations(
            db,
            uid_hash="u1hash",
            context={"device_fingerprint": "dev-abc", "email_hash": "e-h1"},
            source="test",
        )
        register_identity_observations(
            db,
            uid_hash="u2hash",
            context={"device_fingerprint": "dev-abc"},
            source="test",
        )
        db.commit()
        linked = linked_uid_hashes(db, "u1hash")
    assert "u1hash" in linked
    assert "u2hash" in linked


def test_identity_graph_table_created():
    with db_session() as db:
        ensure_identity_graph_tables(db)
        row = db.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='recommend_identity_edges'"
            )
        ).fetchone()
    assert row is not None
