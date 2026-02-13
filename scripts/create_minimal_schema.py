"""Create a minimal set of tables used by tests when using SQLite fallback.
This script uses the project's db engine (src.app.models.db.get_engine) and
applies simple CREATE TABLE IF NOT EXISTS statements compatible with SQLite.
"""
from sqlalchemy import text
from src.app.models.db import get_engine
import os

schema_sql = """
CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  phone TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  sku TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  price_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  specs TEXT,
  active INTEGER DEFAULT 1,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  stock INT NOT NULL,
  warehouse TEXT DEFAULT 'default',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS draft_orders (
  id TEXT PRIMARY KEY,
  customer_id TEXT,
  line_items TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  draft_order_id TEXT,
  customer_id TEXT,
  total_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'pending_payment',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_sessions (
  id TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  order_id TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decision_logs (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT DEFAULT 'infinity',
  system_from TEXT DEFAULT CURRENT_TIMESTAMP,
  system_to TEXT DEFAULT 'infinity',
  input_data TEXT NOT NULL,
  retrieved_context TEXT,
  agent_reasoning TEXT,
  proposed_action TEXT,
  policy_version TEXT NOT NULL,
  approval_required INTEGER,
  approved_by TEXT,
  approved_at TEXT,
  execution_status TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS security_events (
  id TEXT PRIMARY KEY,
  event_time TEXT DEFAULT CURRENT_TIMESTAMP,
  path TEXT,
  severity TEXT,
  verdict_score INT,
  details TEXT,
  escalated INTEGER DEFAULT 0,
  blocked INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  event_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT,
  severity TEXT,
  title TEXT,
  description TEXT,
  status TEXT DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS ragas_eval_results (
  eval_id TEXT PRIMARY KEY,
  decision_log_id TEXT,
  faithfulness DECIMAL(3,2),
  answer_relevance DECIMAL(3,2),
  context_precision DECIMAL(3,2),
  context_recall DECIMAL(3,2),
  evaluated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  evaluator_model TEXT
);
"""


def apply_schema():
    # Remove any existing fallback sqlite DB files to ensure a clean state
    try:
        runs_db = os.path.join(os.getcwd(), "runs", "test_db.sqlite")
        if os.path.exists(runs_db):
            os.remove(runs_db)
    except Exception:
        pass
    # Some tests create their own file-named DBs in repo root — remove common ones
    try:
        tag_db = os.path.join(os.getcwd(), "test_sqlite_security_tags.sqlite")
        if os.path.exists(tag_db):
            os.remove(tag_db)
    except Exception:
        pass

    engine = get_engine()
    with engine.connect() as conn:
        for stmt in [s.strip() for s in schema_sql.split(";") if s.strip()]:
            conn.execute(text(stmt))
        conn.commit()


if __name__ == "__main__":
    apply_schema()
    print("Minimal schema applied")
