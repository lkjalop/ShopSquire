"""Safe, REVERSIBLE prune of the fulfillment-case queue — for a clean demo recording.

The demo/admin procurement queue accumulates test-pollution cases over a session (100+). This tool
clears them WITHOUT data loss: it always dumps every affected row to a timestamped JSON backup FIRST,
then deletes, and can restore that backup verbatim. It targets the app's own configured DB (via
db_session), so it hits exactly the database the running backend uses — no path guessing.

Tables (bitemporal case store):
  • fulfillment_case          — case identity + current status (what the admin queue lists)
  • fulfillment_case_version  — one immutable row per transition (the audit history)

Usage (run from repo root, same venv as the backend):
  python scripts/prune_fulfillment_cases.py --dry-run           # show what WOULD be pruned, touch nothing
  python scripts/prune_fulfillment_cases.py                     # backup ALL, then delete ALL
  python scripts/prune_fulfillment_cases.py --keep <id> <id>    # backup+delete all EXCEPT these case ids
  python scripts/prune_fulfillment_cases.py --older-than-days 1 # only prune cases untouched for >1 day
  python scripts/prune_fulfillment_cases.py --restore backups/fulfillment_cases_<ts>.json   # UNDO

Notes:
  • Backups land in ./backups/ (created if absent). Restore re-INSERTs skipping rows that already exist.
  • This prunes ONLY the two case tables. Related demo tables (procurement_notifications, outbound_message,
    supplier_oob_events) are left alone — they key off case_id and simply won't resolve to a pruned case.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# make `src...` importable when run from the repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text  # noqa: E402

from src.app.models.db import db_session  # noqa: E402

CASE_TABLE = "fulfillment_case"
VERSION_TABLE = "fulfillment_case_version"
BACKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))


def _rows_as_dicts(result) -> list[dict]:
    cols = list(result.keys())
    return [dict(zip(cols, row)) for row in result.fetchall()]


def _select_case_ids(db, *, keep: set[str], older_than_days: int | None) -> list[str]:
    rows = _rows_as_dicts(db.execute(text(f"SELECT id, updated_at FROM {CASE_TABLE}")))
    ids: list[str] = []
    cutoff = None
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_days * 86400
    for r in rows:
        cid = str(r.get("id") or "")
        if not cid or cid in keep:
            continue
        if cutoff is not None:
            # updated_at is 'YYYY-MM-DD HH:MM:SS' (UTC) — keep rows newer than the cutoff
            ts = _parse_ts(r.get("updated_at"))
            if ts is not None and ts >= cutoff:
                continue
        ids.append(cid)
    return ids


def _parse_ts(v) -> float | None:
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(str(v)[:26], fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _dump_backup(db, case_ids: list[str]) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"fulfillment_cases_{ts}.json")
    ph = ",".join(f":id{i}" for i in range(len(case_ids)))
    params = {f"id{i}": cid for i, cid in enumerate(case_ids)}
    cases = _rows_as_dicts(db.execute(text(f"SELECT * FROM {CASE_TABLE} WHERE id IN ({ph})"), params))
    versions = _rows_as_dicts(db.execute(text(f"SELECT * FROM {VERSION_TABLE} WHERE case_id IN ({ph})"), params))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"created_at": ts, "case_ids": case_ids,
                   CASE_TABLE: cases, VERSION_TABLE: versions}, f, indent=2, default=str)
    return path


def _delete(db, case_ids: list[str]) -> tuple[int, int]:
    ph = ",".join(f":id{i}" for i in range(len(case_ids)))
    params = {f"id{i}": cid for i, cid in enumerate(case_ids)}
    v = db.execute(text(f"DELETE FROM {VERSION_TABLE} WHERE case_id IN ({ph})"), params).rowcount
    c = db.execute(text(f"DELETE FROM {CASE_TABLE} WHERE id IN ({ph})"), params).rowcount
    return c, v


def _restore(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    restored_c = restored_v = 0
    with db_session() as db:
        for table, key in ((CASE_TABLE, "id"), (VERSION_TABLE, "id")):
            for row in data.get(table, []):
                exists = db.execute(text(f"SELECT 1 FROM {table} WHERE {key}=:k"),
                                    {"k": row.get(key)}).fetchone()
                if exists:
                    continue
                cols = list(row.keys())
                collist = ",".join(cols)
                vallist = ",".join(f":{c}" for c in cols)
                db.execute(text(f"INSERT INTO {table} ({collist}) VALUES ({vallist})"), row)
                if table == CASE_TABLE:
                    restored_c += 1
                else:
                    restored_v += 1
        db.commit()
    print(f"restored {restored_c} case(s) + {restored_v} version(s) from {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Safe, reversible prune of the fulfillment-case queue.")
    ap.add_argument("--dry-run", action="store_true", help="show what would be pruned; touch nothing")
    ap.add_argument("--keep", nargs="*", default=[], help="case ids to KEEP (never pruned)")
    ap.add_argument("--older-than-days", type=int, default=None, help="only prune cases untouched for > N days")
    ap.add_argument("--restore", metavar="FILE", help="undo: re-insert rows from a backup dump")
    args = ap.parse_args()

    if args.restore:
        _restore(args.restore)
        return 0

    keep = {str(k) for k in (args.keep or [])}
    with db_session() as db:
        ids = _select_case_ids(db, keep=keep, older_than_days=args.older_than_days)
        total = db.execute(text(f"SELECT COUNT(*) FROM {CASE_TABLE}")).scalar() or 0
        print(f"cases in queue: {total} | matched for prune: {len(ids)} | keeping: {len(keep)}")
        if not ids:
            print("nothing to prune.")
            return 0
        if args.dry_run:
            for cid in ids[:20]:
                print(f"  would prune {cid}")
            if len(ids) > 20:
                print(f"  ... and {len(ids) - 20} more")
            print("DRY RUN — nothing deleted.")
            return 0
        backup = _dump_backup(db, ids)
        c, v = _delete(db, ids)
        db.commit()
        print(f"backed up to {backup}")
        print(f"pruned {c} case(s) + {v} version row(s). Undo: --restore {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
