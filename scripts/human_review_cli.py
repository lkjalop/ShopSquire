"""CLI for inspecting and marking human-review DB tasks.

Usage:
  python scripts/human_review_cli.py list
  python scripts/human_review_cli.py pop
  python scripts/human_review_cli.py review <task_id> <reviewer> [notes]
"""
import sys
import json
from sqlalchemy import text
from src.app.models.db import db_session


def _list_pending(limit: int = 20):
    with db_session() as db:
        rows = db.execute(
            text(
                "SELECT id, case_id, status, reviewer_id, created_at, updated_at FROM human_review_tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT :lim"
            ),
            {"lim": limit},
        ).mappings().all()
        return [dict(r) for r in rows]


def _pop_first():
    with db_session() as db:
        row = db.execute(
            text("SELECT id, case_id, status FROM human_review_tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
        ).mappings().first()
        if not row:
            return None
        db.execute(text("UPDATE human_review_tasks SET status = 'in_review' WHERE id = :id"), {"id": row["id"]})
        try:
            db.commit()
        except Exception:
            pass
        return dict(row)


def _mark_reviewed(task_id: str, reviewer: str, notes: str = ""):
    with db_session() as db:
        db.execute(
            text("UPDATE human_review_tasks SET status = 'reviewed', reviewer_id = :rev, notes = :notes WHERE id = :id"),
            {"id": task_id, "rev": reviewer, "notes": notes},
        )
        try:
            db.commit()
        except Exception:
            pass
        return {"id": task_id, "status": "reviewed", "reviewer_id": reviewer, "notes": notes}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"

    if cmd == "list":
        items = _list_pending()
        print(json.dumps(items, indent=2, ensure_ascii=False))
        return

    if cmd == "pop":
        item = _pop_first()
        print(json.dumps(item or {"status": "none"}, indent=2, ensure_ascii=False))
        return

    if cmd == "review" and len(argv) >= 4:
        task_id = argv[2]
        reviewer = argv[3]
        notes = argv[4] if len(argv) > 4 else ""
        out = _mark_reviewed(task_id, reviewer, notes)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
