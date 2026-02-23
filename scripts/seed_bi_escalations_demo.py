from __future__ import annotations

"""
Deterministic local demo seed for Merchant BI + Escalations.

Usage:
  python scripts/seed_bi_escalations_demo.py
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import text as sql_text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.models.db import db_session
from scripts.seed_demo_data import (
    seed_customers,
    seed_products,
    seed_orders,
    seed_decisions,
    seed_security_events,
)


INCIDENTS = [
    {
        "id": "53328e1d261449c4881694faf1e66112",
        "event_id": "esi-113717c1b6ae492193ef0a0bacb17915",
        "created_by": "system",
        "severity": "high",
        "title": "Executive Impersonation (Reply-To Mismatch)",
        "description": json.dumps(
            {
                "summary": "Supplier payment-change request from trusted domain failed reply-to alignment.",
                "trace_id": "trace-email-demo-01",
                "matrix_required": True,
            }
        ),
        "status": "open",
    },
    {
        "id": "b2b84aea-a300-4983-b2de-c563593ddda3",
        "event_id": "esi-7cc6714a19824f38ba2a3e26f3cc982c",
        "created_by": "system",
        "severity": "high",
        "title": "Compromised Supplier Thread Hijack",
        "description": json.dumps(
            {
                "summary": "Same-domain account takeover signs with remittance-change wording in attachment OCR.",
                "trace_id": "trace-email-demo-02",
                "matrix_required": True,
            }
        ),
        "status": "review",
    },
]


def _seed_incidents() -> None:
    now = datetime.now(timezone.utc)
    with db_session() as db:
        for idx, row in enumerate(INCIDENTS):
            created_at = (now - timedelta(minutes=(idx + 1) * 3)).isoformat()
            db.execute(
                sql_text(
                    """
                    INSERT INTO incidents (id, event_id, created_at, created_by, severity, title, description, status)
                    VALUES (:id, :event_id, :created_at, :created_by, :severity, :title, :description, :status)
                    ON CONFLICT(id) DO UPDATE SET
                      event_id = excluded.event_id,
                      severity = excluded.severity,
                      title = excluded.title,
                      description = excluded.description,
                      status = excluded.status
                    """
                ),
                {**row, "created_at": created_at},
            )
        db.commit()


def _seed_incident_chat() -> None:
    out_dir = Path("tmp/incidents_chat")
    out_dir.mkdir(parents=True, exist_ok=True)
    base_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    for idx, inc in enumerate(INCIDENTS):
        p = out_dir / f"{inc['id']}.ndjson"
        rows = [
            {
                "incident_id": inc["id"],
                "role": "assistant",
                "message": "Incident room opened. Agent findings attached to this case.",
                "ts": base_ts - (idx + 2) * 5000,
                "meta": {"seeded": True},
            },
            {
                "incident_id": inc["id"],
                "role": "buyer",
                "message": "Please confirm whether this supplier account is compromised.",
                "ts": base_ts - (idx + 1) * 3000,
                "meta": {"seeded": True},
            },
        ]
        with p.open("w", encoding="utf-8") as f:
            for rec in rows:
                f.write(json.dumps(rec) + "\n")


def main() -> None:
    with db_session() as db:
        seed_customers(db)
        seed_products(db)
        seed_orders(db)
        seed_decisions(db)
        seed_security_events(db)
        db.commit()
    _seed_incidents()
    _seed_incident_chat()
    print("Seeded deterministic BI + escalations demo data.")


if __name__ == "__main__":
    main()
