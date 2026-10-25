"""Migrate and seed an explicit SQLite demo database; never select the root DB implicitly."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / '.artifacts/local-demo.sqlite3')
    parser.add_argument('--seed', action='store_true')
    args = parser.parse_args()
    path = args.database.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix('.backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
    env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + path.as_posix(),
           'DATABASE_URL_RO': 'sqlite:///' + path.as_posix(), 'APP_ENV': 'local'}
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, env=env, check=True)
    if args.seed:
        for module in ('scripts.seed_demo_data', 'scripts.seed_portable_catalog', 'scripts.seed_suppliers',
                       'scripts.bootstrap_sold_taxonomy'):
            subprocess.run([sys.executable, '-m', module], cwd=ROOT, env=env, check=True)
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'conversation_case_state', 'shopping_cases', 'agent_run_event', 'market_source_watermark'}
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError('demo_schema_missing:' + ','.join(missing))
    print(json.dumps({'database': str(path), 'schema_ready': True, 'seed_requested': args.seed}))


if __name__ == '__main__':
    main()
