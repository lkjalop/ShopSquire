from __future__ import annotations

import time
import uuid

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services import webhook_dispatcher as wd


def test_webhook_storm_moves_failed_deliveries_to_dlq(monkeypatch):
    class _Down:
        @staticmethod
        def post(*_a, **_k):
            raise RuntimeError("provider_down")

    monkeypatch.setattr(wd, "requests", _Down())
    for i in range(12):
        wd.enqueue_webhook(
            f"storm-{uuid.uuid4().hex}",
            "https://hooks.invalid/storm",
            {"i": i},
            max_attempts=1,
            tenant_id="chaos-tenant",
        )

    wd.start_worker(poll_interval=0.05)
    time.sleep(0.6)
    wd.stop_worker()

    with db_session() as db:
        rows = db.execute(
            text(
                "SELECT status, COUNT(1) FROM webhook_deliveries WHERE tenant_id = :tenant GROUP BY status"
            ),
            {"tenant": "chaos-tenant"},
        ).fetchall()
    counts = {str(r[0]): int(r[1] or 0) for r in (rows or [])}
    assert int(counts.get("dlq", 0)) >= 10

