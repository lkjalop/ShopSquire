"""Demo-DB hygiene — report (default) or purge (--purge) the residue that would muddy a recording.

What it targets, and ONLY this (conservative by design):
  1. VERIFICATION artifacts from engineering test runs: fulfillment cases + versions + trace events
     whose source_trace_id/order_group matches the known verification prefixes (demo-gt-, demo-amend-,
     demo-enrich-, wake-verify-, multi-sup-, mi-verify). These are QUOTE_DRAFTED test cases that would
     appear in the operator case queue on camera.
  2. seed:verify competitor observations (--purge-seed) — remove once REAL browser-recorded prices are
     imported, so every observation is genuinely human-recorded.
It REPORTS null-source_trace_id and superseded cases but never touches them (self-heal + history).

Usage:  python scripts/demo_db_hygiene.py            # dry-run report
        python scripts/demo_db_hygiene.py --purge    # remove verification cases/events
        python scripts/demo_db_hygiene.py --purge --purge-seed   # also drop seed:verify observations
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import text

from src.app.models.db import db_session

_VERIFY_PREFIXES = ("demo-gt-", "demo-amend-", "demo-enrich-", "wake-verify-", "multi-sup-", "mi-verify")


def main() -> None:
    purge = "--purge" in sys.argv
    purge_seed = "--purge-seed" in sys.argv
    like_clauses = " OR ".join(f"source_trace_id LIKE '{p}%'" for p in _VERIFY_PREFIXES)
    ev_like = " OR ".join(f"trace_id LIKE '{p}%'" for p in _VERIFY_PREFIXES)
    with db_session() as db:
        case_ids = [r[0] for r in db.execute(text(
            f"SELECT id FROM fulfillment_case WHERE {like_clauses}")).fetchall()]
        n_events = db.execute(text(
            f"SELECT COUNT(*) FROM decision_trace_events WHERE {ev_like}")).scalar() or 0
        n_seed = db.execute(text(
            "SELECT COUNT(*) FROM competitor_observation WHERE source='seed:verify'")).scalar() or 0
        n_null = db.execute(text(
            "SELECT COUNT(*) FROM fulfillment_case WHERE source_trace_id IS NULL")).scalar() or 0
        n_sup = db.execute(text(
            "SELECT COUNT(*) FROM fulfillment_case WHERE status='SUPERSEDED'")).scalar() or 0

        print(f"verification cases      : {len(case_ids)}  (trace prefixes: {', '.join(_VERIFY_PREFIXES)})")
        print(f"verification trace rows : {n_events}")
        print(f"seed:verify observations: {n_seed}")
        print(f"null-trace cases        : {n_null}  (left alone — self-heal on next confirm)")
        print(f"superseded cases        : {n_sup}  (left alone — amendment history)")

        if not purge:
            print("\ndry-run only. Re-run with --purge (and --purge-seed after importing real prices).")
            return

        if case_ids:
            marks = ",".join(f"'{c}'" for c in case_ids)
            db.execute(text(f"DELETE FROM fulfillment_case_version WHERE case_id IN ({marks})"))
            db.execute(text(f"DELETE FROM fulfillment_case WHERE id IN ({marks})"))
        db.execute(text(f"DELETE FROM decision_trace_events WHERE {ev_like}"))
        removed_seed = 0
        if purge_seed:
            removed_seed = db.execute(text(
                "DELETE FROM competitor_observation WHERE source='seed:verify'")).rowcount or 0
        db.commit()
        print(f"\npurged: {len(case_ids)} case(s) + versions, {n_events} trace row(s)"
              + (f", {removed_seed} seed observation(s)" if purge_seed else
                 " (seed:verify kept — pass --purge-seed after importing real prices)"))


if __name__ == "__main__":
    main()
