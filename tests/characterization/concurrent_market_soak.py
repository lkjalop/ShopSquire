"""Concurrent canonical market-fact lab using an isolated synthetic tenant.

This measures ingestion, deduplication, tenant isolation, data quality and BI
cohorts. It does not claim buyer relevance or canary equivalence.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.app.models.db import get_engine
from src.app.services.market_facts import record_marketing_event
from src.app.services.market_metrics import summarize_marketing_facts


EVENT_PATHS = (
    ("view_item", "click", "add_to_cart", "purchase", "view_item"),
    ("view_item", "click", "add_to_cart", "view_item", "view_item"),
    ("view_item", "click", "view_item", "view_item", "view_item"),
)
SKUS = ("LAP-69763798", "LAP-433AB371", "TAB-WACOM-01")


def _write_user(session_factory, *, tenant: str, user: int, turns: int, seed: int) -> dict:
    rng = random.Random(seed + user)
    path = EVENT_PATHS[user % len(EVENT_PATHS)]
    session_id = f"synthetic-session-{user}"
    campaign = f"synthetic-campaign-{user % 2}"
    sku = SKUS[user % len(SKUS)]
    written = 0
    errors = []
    for turn in range(turns):
        event = path[turn % len(path)]
        occurred = datetime.now(timezone.utc) + timedelta(milliseconds=turn)
        fact = {
            "tenant_id": tenant,
            "deduplication_id": f"{tenant}:{user}:{turn}",
            "source_system": "synthetic_concurrent_soak",
            "source_record_id": f"user-{user}:turn-{turn}",
            "event_type": event,
            "occurred_at": occurred.isoformat(),
            "session_id": session_id,
            "subject_hash": f"synthetic-user-{user}",
            "sku": sku,
            "campaign_id": campaign,
            "channel": "synthetic",
            "value": 1199.0 if event == "purchase" else None,
            "currency": "AUD" if event == "purchase" else None,
            "quantity": 1,
            "consent_state": "granted",
            "attribution_window": "7d_click",
            "confidence": 1.0,
            "freshness_policy": "synthetic_only",
            "provenance_chain": ["synthetic_lab", session_id, f"turn:{turn}"],
        }
        for attempt in range(5):
            db = session_factory()
            try:
                written += int(record_marketing_event(db, fact))
                break
            except Exception as exc:
                db.rollback()
                if attempt == 4:
                    errors.append(f"turn-{turn}:{type(exc).__name__}:{str(exc)[:80]}")
                time.sleep(0.02 * (attempt + 1) + rng.random() * 0.01)
            finally:
                db.close()
    return {"user": user, "written": written, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--turns", type=int, default=5)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260720)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--output", default="tmp/synthetic_soak/concurrent_market_soak.json")
    args = parser.parse_args()
    tenant = f"synthetic-market-{uuid.uuid4().hex[:10]}"
    engine = get_engine()
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with ThreadPoolExecutor(max_workers=min(args.workers, args.users)) as pool:
        futures = [pool.submit(_write_user, sessions, tenant=tenant, user=user,
                               turns=args.turns, seed=args.seed) for user in range(args.users)]
        workers = [future.result() for future in as_completed(futures)]
    db = sessions()
    try:
        report = summarize_marketing_facts(db, tenant_id=tenant)
        report["lab"] = {
            "users": args.users, "turns_per_user": args.turns, "workers": args.workers,
            "expected_events": args.users * args.turns,
            "written_events": sum(item["written"] for item in workers),
            "write_errors": [error for item in workers for error in item["errors"]],
            "synthetic_tenant": tenant,
            "production_canary_equivalent": False,
        }
        if not args.persist:
            db.execute(text("DELETE FROM marketing_event_fact WHERE tenant_id=:tenant"), {"tenant": tenant})
            db.commit()
            report["lab"]["cleaned_up"] = True
    finally:
        db.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "event_count": report["event_count"],
                      "quality": report["data_quality"], "insights": report["insights"],
                      "errors": report["lab"]["write_errors"]}))
    return 1 if report["lab"]["write_errors"] or report["event_count"] != args.users * args.turns else 0


if __name__ == "__main__":
    raise SystemExit(main())
