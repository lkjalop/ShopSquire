import os
import json
import asyncio
from src.app.services.notifications import NotificationService
from src.app.models.db import db_session
from src.app.models import db as dbmod
from src.app.models.init_db import ensure_metadata
from sqlalchemy import create_engine


def test_notification_logs_decision(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path}/notify.sqlite"
    os.environ["DATABASE_URL"] = url
    dbmod.set_engine(create_engine(url, future=True))
    ensure_metadata()
    ns = NotificationService()
    asyncio.get_event_loop().run_until_complete(ns.send_notification(
        event="case_created",
        context={"case_id": "C1", "customer_email": "alice@example.com", "track_url": "/cases/C1"},
        channels=["email"],
    ))
    with db_session() as db:
        row = db.execute("SELECT agent_name, input_data, proposed_action FROM decision_logs WHERE agent_name = 'notification_agent' ORDER BY system_from DESC LIMIT 1").fetchone()
        assert row is not None
        input_data = json.loads(row[1])
        action = json.loads(row[2])
        assert input_data.get("event") == "case_created"
        assert action.get("dispatch") is True
