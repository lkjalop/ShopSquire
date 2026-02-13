from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import create_engine, text
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire",
    )
    engine = create_engine(db_url, future=True)
    ddl = [
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS guest_email TEXT",
        """
        CREATE TABLE IF NOT EXISTS oauth_identities (
          id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          provider_user_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          email TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(provider, provider_user_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS oauth_states (
          state TEXT PRIMARY KEY,
          return_to TEXT,
          expires_at TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                # SQLite does not support IF NOT EXISTS on ALTER COLUMN.
                if "sqlite" in db_url:
                    try:
                        conn.execute(text("ALTER TABLE orders ADD COLUMN guest_email TEXT"))
                    except Exception:
                        pass
                else:
                    raise exc
    print(f"Migration complete at {datetime.utcnow().isoformat()} for {db_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
