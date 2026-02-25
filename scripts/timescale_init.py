import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("DATABASE_URL not set; aborting.")
    sys.exit(1)

engine = create_engine(DB_URL, future=True)

migrations = [
    Path("db/timescale/001_enable_timescaledb.sql"),
    Path("db/timescale/002_hypertables.sql"),
    Path("db/timescale/003_continuous_aggregates.sql"),
]

for mig in migrations:
    if not mig.exists():
        print(f"Missing migration: {mig}")
        continue
    sql = mig.read_text(encoding="utf-8")
    print(f"Applying {mig}...")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    print(f"Applied {mig}.")

print("Timescale migrations applied.")
