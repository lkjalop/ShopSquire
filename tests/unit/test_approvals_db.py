from src.app.routers.approvals import enqueue_approval, list_pending, approve
from src.app.models.db import db_session


def test_enqueue_and_list_pending():
    # Create approval and ensure it appears in pending list
    aid = enqueue_approval("test.capability", {"foo": "bar"}, reason="unit-test", created_by="merchant")
    res = list_pending(role="merchant")
    pending = res.get("pending") or []
    ids = [p.get("id") for p in pending]
    assert aid in ids


def test_approve_marks_db():
    aid = enqueue_approval("test.capability", {"x": 1}, reason="approve-test", created_by="owner")
    resp = approve(aid, role="owner")
    assert resp.get("approved") is True
    # Verify DB status
    with db_session() as db:
        row = db.execute("SELECT status, approved_by FROM approvals WHERE id = :id", {"id": aid}).fetchone()
        assert row is not None
        assert row[0] == "approved"