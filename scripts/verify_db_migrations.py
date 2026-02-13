from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Upgrade DB to Alembic head and run shadow checks.")
    ap.add_argument("--db-url", help="Database URL (overrides DATABASE_URL env)")
    ap.add_argument("--no-upgrade", action="store_true", help="Skip upgrade, only run checks")
    args = ap.parse_args()

    db_url = args.db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL required (or pass --db-url)")
        return 2

    if not args.no_upgrade:
        from alembic.config import Config
        from alembic import command

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        print(f"[verify] alembic upgrade head (db_url={db_url})")
        command.upgrade(cfg, "head")

    # Shadow checks (fast invariants)
    try:
        import subprocess

        cmd = [sys.executable, "scripts/shadow_migration_check.py", "--db-url", db_url]
        print(f"[verify] running: {' '.join(cmd)}")
        return subprocess.call(cmd)
    except Exception as exc:
        print(f"[verify] failed to run shadow_migration_check: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

