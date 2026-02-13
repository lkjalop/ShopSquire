"""Lightweight dispatcher for pending event_log entries.

Reads pending events and attempts delivery via HTTP webhooks when delivery_url is present.
Updates status and last_attempt.
"""
import json
import time
from typing import Optional
import requests
from sqlalchemy import text

from src.app.models.db import db_session


def dispatch_pending_once(limit: int = 20):
    now = __import__("datetime").datetime.utcnow().isoformat()
    sent = 0
    with db_session() as db:
        rows = db.execute(
            text("SELECT id, type, payload, delivery_url FROM event_log WHERE status = 'pending' ORDER BY created_at ASC LIMIT :limit"),
            {"limit": limit},
        ).fetchall()
        for r in rows:
            evt_id, evt_type, payload, url = r[0], r[1], r[2], r[3]
            ok = False
            if url:
                try:
                    data = json.loads(payload or "{}")
                    resp = requests.post(url, json={"type": evt_type, "payload": data}, timeout=3)
                    ok = resp.status_code < 300
                except Exception:
                    ok = False
            # Update status/last_attempt
            db.execute(
                text("UPDATE event_log SET status = :st, last_attempt = :ts WHERE id = :id"),
                {"st": "sent" if ok else "error", "ts": now, "id": evt_id},
            )
        db.commit()
    return sent


def run_loop(poll_seconds: int = 5, max_cycles: Optional[int] = None):
    cycles = 0
    while True:
        dispatch_pending_once(limit=20)
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        time.sleep(poll_seconds)
