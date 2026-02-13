import uuid
from src.app.models.db import db_session


def test_human_review_insert_and_query():
    hr_id = f"hr-{uuid.uuid4().hex}"
    case_id = f"case-{uuid.uuid4().hex}"
    with db_session() as db:
        db.execute("INSERT INTO human_review_tasks (id, case_id, decision_id, ticket_id, status, created_at) VALUES (:id, :case_id, :decision_id, :ticket_id, :status, CURRENT_TIMESTAMP)",
                   {"id": hr_id, "case_id": case_id, "decision_id": "dec-1", "ticket_id": None, "status": "pending"})
        db.commit()
    with db_session() as db:
        res = db.execute("SELECT id, case_id, status FROM human_review_tasks WHERE id = :id", {"id": hr_id}).fetchone()
        assert res is not None
        assert res[0] == hr_id
        assert res[1] == case_id
        assert res[2] in ("pending", "open")
