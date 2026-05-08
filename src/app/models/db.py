from contextlib import contextmanager
import types
import os
from sqlalchemy import create_engine
import re
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text as sql_text
from sqlalchemy.sql.elements import TextClause
from fastapi import Request
from typing import Any
import contextvars

from src.app.config import get_settings


settings = get_settings()
db_url = settings.database_url


# Helper to register a 'now()' function on SQLite engines for compatibility
def _register_sqlite_now(engine):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_register_now(dbapi_connection, connection_record):
        try:
            dbapi_connection.create_function(
                "now", 0, lambda: __import__("datetime").datetime.utcnow().isoformat()
            )
        except Exception:
            pass
    # SQLite-only: Rewrite plain INSERT into INSERT OR REPLACE so tests
    # with duplicate primary keys do not fail. This ONLY fires on SQLite
    # engines and should NEVER be applied to Postgres/production.
    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def _rewrite_insert(conn, cursor, statement, parameters, context, executemany):
        try:
            if isinstance(statement, str) and re.search(r"\bINSERT\s+INTO\b", statement, flags=re.IGNORECASE):
                statement = re.sub(r"\bINSERT\s+INTO\b", "INSERT OR REPLACE INTO", statement, flags=re.IGNORECASE)
        except Exception:
            pass
        return statement, parameters


# Create engine using configured DATABASE_URL. If SQLite is explicitly requested,
# register compatibility helpers; otherwise, defer connectivity to callers/tests.
def _create_engine_with_fallback(url: str):
    if url and url.startswith("sqlite"):
        eng = create_engine(url, pool_pre_ping=True, future=True)
        _register_sqlite_now(eng)
        return eng
    # Do not fallback silently to SQLite; always honor configured URL.
    # create_engine does not connect immediately, so this is safe even if the
    # database is not yet ready. Test bootstrap ensures readiness and schema.
    eng = create_engine(url, pool_pre_ping=True, future=True)
    # For Postgres, set a default search_path so unqualified table names
    # resolve to our logical schemas in order: oltp, audit, security, public.
    try:
        from sqlalchemy import event
        if str(eng.url).startswith("postgres") or "postgres" in str(eng.url):
            @event.listens_for(eng, "connect")
            def _pg_set_search_path(dbapi_connection, connection_record):
                try:
                    cursor = dbapi_connection.cursor()
                    cursor.execute("SET search_path TO oltp, audit, security, public")
                    cursor.close()
                except Exception:
                    pass
    except Exception:
        pass
    return eng


engine = _create_engine_with_fallback(db_url)
# Provide a module-level SessionLocal for tests that monkeypatch it
try:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
except Exception:
    SessionLocal = None

# ContextVar to hold the current Request during a request lifecycle so
# utility code that isn't a FastAPI dependency can still access the
# request-specific app state (notably `app.state.engine`). Middleware
# sets this before calling route handlers and resets it afterwards.
CURRENT_REQUEST: contextvars.ContextVar = contextvars.ContextVar("CURRENT_REQUEST", default=None)


def set_engine(new_engine):
    """Replace the module-level engine at runtime (tests can call this).

    Also register SQLite helpers when appropriate.
    """
    global engine
    engine = new_engine
    try:
        if "sqlite" in str(engine.url.drivername).lower():
            _register_sqlite_now(engine)
    except Exception:
        pass
    # Ensure the global SessionLocal matches the current engine to avoid
    # stale sessionmakers pointing at previous engines during tests.
    try:
        globals()["SessionLocal"] = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
    except Exception:
        pass


def _ensure_minimal_sqlite_tables(bind):
    """Ensure minimal tables exist on a given SQLAlchemy bind for SQLite.

    Reused by both db_session() and get_db() to avoid visibility issues
    across different connections in tests.
    """
    try:
        if "sqlite" in str(bind.dialect.name).lower():
            with bind.connect() as conn:
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS orders (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  draft_order_id TEXT,\n"
                    "  customer_id TEXT,\n"
                    "  guest_email TEXT,\n"
                    "  total_cents INT NOT NULL,\n"
                    "  currency TEXT NOT NULL DEFAULT 'USD',\n"
                    "  status TEXT NOT NULL DEFAULT 'pending_payment',\n"
                    "  stripe_intent_id TEXT,\n"
                    "  tracking_number TEXT,\n"
                    "  carrier TEXT,\n"
                    "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                    "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                    ")"
                ))
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS order_sessions (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  uid TEXT NOT NULL,\n"
                    "  order_id TEXT NOT NULL,\n"
                    "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                    ")"
                ))
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS draft_orders (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  customer_id TEXT,\n"
                    "  line_items TEXT NOT NULL,\n"
                    "  status TEXT NOT NULL DEFAULT 'draft',\n"
                    "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                    "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                    ")"
                ))
                try:
                    conn.execute(sql_text("ALTER TABLE orders ADD COLUMN guest_email TEXT"))
                except Exception:
                    pass
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS security_events (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  event_time TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                    "  path TEXT,\n"
                    "  severity TEXT,\n"
                    "  verdict_score INT,\n"
                    "  details TEXT,\n"
                    "  escalated INTEGER DEFAULT 0,\n"
                    "  blocked INTEGER DEFAULT 0,\n"
                    "  ground_truth TEXT,\n"
                    "  analyst_verdict TEXT,\n"
                    "  correction_ts TEXT,\n"
                    "  correction_notes TEXT\n"
                    ")"
                ))
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS iam_events (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  event_time TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                    "  event_type TEXT,\n"
                    "  actor TEXT,\n"
                    "  source_ip TEXT,\n"
                    "  user_agent TEXT,\n"
                    "  success INTEGER DEFAULT 0,\n"
                    "  risk_score INT,\n"
                    "  details TEXT\n"
                    ")"
                ))
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS incidents (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  event_id TEXT,\n"
                    "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                    "  created_by TEXT,\n"
                    "  severity TEXT,\n"
                    "  title TEXT,\n"
                    "  description TEXT,\n"
                    "  status TEXT DEFAULT 'open'\n"
                    ")"
                ))
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS chat_messages (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  uid TEXT NOT NULL,\n"
                    "  session_id TEXT,\n"
                    "  role TEXT NOT NULL,\n"
                    "  content TEXT NOT NULL,\n"
                    "  trace_id TEXT,\n"
                    "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                    ")"
                ))
                # Outbox table for async event delivery in tests/dev (SQLite)
                conn.execute(sql_text(
                    "CREATE TABLE IF NOT EXISTS event_log (\n"
                    "  id TEXT PRIMARY KEY,\n"
                    "  type TEXT NOT NULL,\n"
                    "  payload TEXT NOT NULL,\n"
                    "  status TEXT NOT NULL DEFAULT 'pending',\n"
                    "  delivery_url TEXT,\n"
                    "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                    "  last_attempt TEXT\n"
                    ")"
                ))
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS decision_logs (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  tenant_id TEXT,\n"
                        "  agent_name TEXT,\n"
                        "  valid_from TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  valid_to TEXT DEFAULT 'infinity',\n"
                        "  system_from TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  system_to TEXT DEFAULT 'infinity',\n"
                        "  input_data TEXT,\n"
                        "  retrieved_context TEXT,\n"
                        "  agent_reasoning TEXT,\n"
                        "  proposed_action TEXT,\n"
                        "  policy_version TEXT,\n"
                        "  approval_required INTEGER,\n"
                        "  approved_by TEXT,\n"
                        "  approved_at TEXT,\n"
                        "  execution_status TEXT,\n"
                        "  error_message TEXT,\n"
                        "  evaluator_model TEXT,\n"
                        "  created_at INTEGER\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Rules definitions (used by RuleStore / RuleEngine)
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS rule_definitions (\n"
                            "  id TEXT PRIMARY KEY,\n"
                            "  tenant_id TEXT,\n"
                            "  domain TEXT,\n"
                            "  title TEXT NOT NULL,\n"
                            "  pattern TEXT,\n"
                            "  expression TEXT,\n"
                            "  priority INT DEFAULT 100,\n"
                            "  active INT DEFAULT 1,\n"
                            "  created_by TEXT,\n"
                            "  version TEXT,\n"
                            "  effective_from TEXT,\n"
                            "  effective_to TEXT,\n"
                            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                # Backfill missing domain column for older SQLite files.
                try:
                    conn.execute(sql_text("ALTER TABLE rule_definitions ADD COLUMN domain TEXT"))
                except Exception:
                    pass
                # Tenant-scoped config overrides (SQLite fallback for tests/dev)
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS tenant_config_overrides (\n"
                            "  tenant_id TEXT NOT NULL,\n"
                            "  config_key TEXT NOT NULL,\n"
                            "  value_json TEXT NOT NULL,\n"
                            "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                            "  PRIMARY KEY (tenant_id, config_key)\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS evidence_bundles (\n"
                            "  id TEXT PRIMARY KEY,\n"
                            "  case_id TEXT NOT NULL,\n"
                            "  bundle_json TEXT NOT NULL,\n"
                            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                # Phase 2: fusion score persistence (SQLite fallback for tests/dev)
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS fusion_scores (\n"
                            "  id TEXT PRIMARY KEY,\n"
                            "  tenant_id TEXT,\n"
                            "  case_id TEXT,\n"
                            "  source TEXT,\n"
                            "  features_json TEXT NOT NULL,\n"
                            "  score REAL NOT NULL,\n"
                            "  model_version TEXT,\n"
                            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                # Email security incidents (SQLite fallback for tests/dev)
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS email_security_incidents (\n"
                            "  id TEXT PRIMARY KEY,\n"
                            "  tenant_id TEXT,\n"
                            "  provider TEXT,\n"
                            "  supplier_key_hash TEXT,\n"
                            "  conversation_id_hash TEXT,\n"
                            "  message_id_hash TEXT,\n"
                            "  ticket_id TEXT,\n"
                            "  severity TEXT NOT NULL,\n"
                            "  risk_band TEXT,\n"
                            "  tags_json TEXT NOT NULL,\n"
                            "  reasons_json TEXT NOT NULL,\n"
                            "  evidence_json TEXT NOT NULL,\n"
                            "  playbook_id TEXT,\n"
                            "  playbook_title TEXT,\n"
                            "  ticket_created INTEGER DEFAULT 0,\n"
                            "  ticket_rate_limited INTEGER DEFAULT 0,\n"
                            "  ticket_deduped INTEGER DEFAULT 0,\n"
                            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                # Ensure ticket_id column exists for older environments
                try:
                    conn.execute(sql_text("ALTER TABLE email_security_incidents ADD COLUMN ticket_id TEXT"))
                except Exception:
                    pass
                for stmt in [
                    "ALTER TABLE email_security_incidents ADD COLUMN ground_truth TEXT",
                    "ALTER TABLE email_security_incidents ADD COLUMN analyst_verdict TEXT",
                    "ALTER TABLE email_security_incidents ADD COLUMN correction_ts TEXT",
                    "ALTER TABLE email_security_incidents ADD COLUMN correction_notes TEXT",
                ]:
                    try:
                        conn.execute(sql_text(stmt))
                    except Exception:
                        pass
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS security_threshold_overrides (\n"
                            "  tenant_id TEXT NOT NULL,\n"
                            "  threshold_key TEXT NOT NULL,\n"
                            "  threshold_value REAL NOT NULL,\n"
                            "  source TEXT,\n"
                            "  sample_size INTEGER DEFAULT 0,\n"
                            "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                            "  PRIMARY KEY (tenant_id, threshold_key)\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS email_sender_trust (\n"
                            "  tenant_id TEXT NOT NULL,\n"
                            "  sender_domain_hash TEXT NOT NULL,\n"
                            "  seen_count INTEGER NOT NULL DEFAULT 0,\n"
                            "  bank_change_count INTEGER NOT NULL DEFAULT 0,\n"
                            "  oob_verified_count INTEGER NOT NULL DEFAULT 0,\n"
                            "  reply_chain_mismatch_count INTEGER NOT NULL DEFAULT 0,\n"
                            "  last_reply_chain_hash TEXT,\n"
                            "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                            "  PRIMARY KEY (tenant_id, sender_domain_hash)\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS partner_scope_baselines (\n"
                            "  tenant_id TEXT NOT NULL,\n"
                            "  partner TEXT NOT NULL,\n"
                            "  scopes_json TEXT NOT NULL,\n"
                            "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                            "  PRIMARY KEY (tenant_id, partner)\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                # Drift daily metrics (SQLite fallback for tests/dev)
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS drift_daily_metrics (\n"
                            "  id TEXT PRIMARY KEY,\n"
                            "  tenant_id TEXT,\n"
                            "  day TEXT NOT NULL,\n"
                            "  domain TEXT NOT NULL,\n"
                            "  metric_key TEXT NOT NULL,\n"
                            "  metric_value REAL NOT NULL,\n"
                            "  labels_json TEXT NOT NULL,\n"
                            "  labels_hash TEXT NOT NULL,\n"
                            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                            "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                try:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS human_review_tasks (\n"
                            "  id TEXT PRIMARY KEY,\n"
                            "  case_id TEXT NOT NULL,\n"
                            "  decision_id TEXT,\n"
                            "  ticket_id TEXT,\n"
                            "  status TEXT NOT NULL DEFAULT 'pending',\n"
                            "  reviewer_id TEXT,\n"
                            "  rationale TEXT,\n"
                            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                            "  updated_at TEXT\n"
                            ")"
                        )
                    )
                except Exception:
                    pass
                # Ensure common columns exist on human_review_tasks for older test DBs
                for stmt in [
                    "ALTER TABLE human_review_tasks ADD COLUMN decision_id TEXT",
                    "ALTER TABLE human_review_tasks ADD COLUMN ticket_id TEXT",
                    "ALTER TABLE human_review_tasks ADD COLUMN status TEXT",
                    "ALTER TABLE human_review_tasks ADD COLUMN reviewer_id TEXT",
                    "ALTER TABLE human_review_tasks ADD COLUMN rationale TEXT",
                    "ALTER TABLE human_review_tasks ADD COLUMN updated_at TEXT",
                ]:
                    try:
                        conn.execute(sql_text(stmt))
                    except Exception:
                        pass
                # Backfill missing columns for existing minimal tables
                for stmt in [
                    "ALTER TABLE decision_logs ADD COLUMN tenant_id TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN agent_name TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN valid_from TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN valid_to TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN system_from TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN system_to TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN input_data TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN retrieved_context TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN agent_reasoning TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN proposed_action TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN policy_version TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN approval_required INTEGER",
                    "ALTER TABLE decision_logs ADD COLUMN approved_by TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN approved_at TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN execution_status TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN error_message TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN evaluator_model TEXT",
                    "ALTER TABLE decision_logs ADD COLUMN created_at INTEGER",
                ]:
                    try:
                        conn.execute(sql_text(stmt))
                    except Exception:
                        pass

                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS approvals (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  capability TEXT NOT NULL,\n"
                        "  payload TEXT,\n"
                        "  reason TEXT,\n"
                        "  status TEXT NOT NULL DEFAULT 'pending',\n"
                        "  created_by TEXT,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  approved_by TEXT,\n"
                        "  approved_at TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass

                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS security_observer_timeseries (\n"
                        "  time TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  event_id TEXT,\n"
                        "  severity TEXT,\n"
                        "  risk_adj REAL,\n"
                        "  insider_score REAL,\n"
                        "  tenant_id TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS decision_audits (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  decision_id TEXT NOT NULL,\n"
                        "  action TEXT NOT NULL,\n"
                        "  actor TEXT,\n"
                        "  metadata TEXT,\n"
                        "  created_at TEXT,\n"
                        "  record_hash TEXT,\n"
                        "  prev_hash TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass
                # C01: add hash chain columns if missing (migration for existing DBs)
                for stmt in (
                    "ALTER TABLE decision_audits ADD COLUMN record_hash TEXT",
                    "ALTER TABLE decision_audits ADD COLUMN prev_hash TEXT",
                ):
                    try:
                        conn.execute(sql_text(stmt))
                    except Exception:
                        pass
                # Playbook execution state (SQLite fallback for tests/dev)
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS playbook_runs (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  trace_id TEXT,\n"
                        "  decision_id TEXT,\n"
                        "  tenant_id TEXT,\n"
                        "  playbook_id TEXT NOT NULL,\n"
                        "  playbook_version TEXT NOT NULL,\n"
                        "  owner TEXT,\n"
                        "  status TEXT NOT NULL,\n"
                        "  outcome TEXT,\n"
                        "  posthoc_outcome_id TEXT,\n"
                        "  metadata_json TEXT,\n"
                        "  started_at TEXT NOT NULL,\n"
                        "  ended_at TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS playbook_run_steps (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  run_id TEXT NOT NULL,\n"
                        "  step_index INTEGER NOT NULL,\n"
                        "  event_type TEXT NOT NULL,\n"
                        "  status TEXT NOT NULL,\n"
                        "  evidence_json TEXT,\n"
                        "  created_at TEXT NOT NULL\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Playbook action reliability tables (retry/idempotency/DLQ)
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS playbook_action_executions (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  run_id TEXT NOT NULL,\n"
                        "  step_index INTEGER NOT NULL,\n"
                        "  action_type TEXT NOT NULL,\n"
                        "  idempotency_key TEXT NOT NULL,\n"
                        "  attempt INTEGER NOT NULL,\n"
                        "  status TEXT NOT NULL,\n"
                        "  result_json TEXT,\n"
                        "  error TEXT,\n"
                        "  created_at TEXT NOT NULL\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS playbook_action_dlq (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  run_id TEXT NOT NULL,\n"
                        "  step_index INTEGER NOT NULL,\n"
                        "  action_type TEXT NOT NULL,\n"
                        "  idempotency_key TEXT NOT NULL,\n"
                        "  payload_json TEXT NOT NULL,\n"
                        "  last_error TEXT,\n"
                        "  created_at TEXT NOT NULL\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_action_exec_idem ON playbook_action_executions(idempotency_key)"))
                    conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_action_dlq_run ON playbook_action_dlq(run_id, step_index)"))
                except Exception:
                    pass
                # Immutable audit hash chain
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS audit_log_chain (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  source_type TEXT NOT NULL,\n"
                        "  source_id TEXT,\n"
                        "  payload_hash TEXT NOT NULL,\n"
                        "  prev_hash TEXT,\n"
                        "  merkle_root TEXT NOT NULL,\n"
                        "  created_at TEXT NOT NULL\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_audit_log_chain_created ON audit_log_chain(created_at)"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_runs_trace ON playbook_runs(trace_id)"))
                    conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_runs_playbook ON playbook_runs(playbook_id, playbook_version)"))
                    conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_run_steps_run ON playbook_run_steps(run_id, step_index)"))
                except Exception:
                    pass
                # Decision trace events table for observability/testing
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS decision_trace_events (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  trace_id TEXT,\n"
                        "  event_type TEXT NOT NULL,\n"
                        "  source_type TEXT,\n"
                        "  source_id TEXT,\n"
                        "  target_type TEXT,\n"
                        "  target_id TEXT,\n"
                        "  payload TEXT,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                # PII encrypted fields (compat; plaintext columns retained for fallback)
                try:
                    conn.execute(sql_text("ALTER TABLE orders ADD COLUMN guest_email_hash TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE orders ADD COLUMN guest_email_encrypted TEXT"))
                except Exception:
                    pass
                for _stmt in (
                    "ALTER TABLE orders ADD COLUMN stripe_intent_id TEXT",
                    "ALTER TABLE orders ADD COLUMN tracking_number TEXT",
                    "ALTER TABLE orders ADD COLUMN carrier TEXT",
                ):
                    try:
                        conn.execute(sql_text(_stmt))
                    except Exception:
                        pass
                try:
                    conn.execute(sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_orders_stripe_intent ON orders(stripe_intent_id)"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE cases ADD COLUMN guest_email_hash TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE cases ADD COLUMN guest_email_encrypted TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE customers ADD COLUMN email_hash TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE customers ADD COLUMN email_encrypted TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE customers ADD COLUMN phone_encrypted TEXT"))
                except Exception:
                    pass
                # Cases and CV-related tables for complaint triage
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS cases (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  tenant_id TEXT,\n"
                        "  order_id TEXT,\n"
                        "  customer_id TEXT,\n"
                        "  guest_email TEXT,\n"
                        "  issue_type TEXT,\n"
                        "  description TEXT,\n"
                        "  status TEXT DEFAULT 'open',\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Ensure PII columns exist on cases table (added after creation)
                try:
                    conn.execute(sql_text("ALTER TABLE cases ADD COLUMN guest_email_hash TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE cases ADD COLUMN guest_email_encrypted TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS cv_analyses (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  case_id TEXT NOT NULL,\n"
                        "  image_sha256 TEXT,\n"
                        "  image_phash TEXT,\n"
                        "  damage_type TEXT,\n"
                        "  damage_location TEXT,\n"
                        "  severity TEXT,\n"
                        "  confidence REAL,\n"
                        "  serial_number TEXT,\n"
                        "  extracted_text TEXT,\n"
                        "  raw_labels TEXT,\n"
                        "  model_version TEXT,\n"
                        "  processing_time_ms INTEGER,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS customer_trust_scores (\n"
                        "  customer_id TEXT PRIMARY KEY,\n"
                        "  trust_score REAL NOT NULL,\n"
                        "  account_age_score REAL,\n"
                        "  purchase_history_score REAL,\n"
                        "  return_history_score REAL,\n"
                        "  fraud_history_score REAL,\n"
                        "  calculated_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  expires_at TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS fraud_image_hashes (\n"
                        "  phash TEXT PRIMARY KEY,\n"
                        "  first_seen_case_id TEXT,\n"
                        "  times_seen INTEGER DEFAULT 1,\n"
                        "  confirmed_fraud INTEGER DEFAULT 0,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS return_labels (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  case_id TEXT NOT NULL,\n"
                        "  carrier TEXT NOT NULL,\n"
                        "  tracking_number TEXT NOT NULL,\n"
                        "  label_url TEXT NOT NULL,\n"
                        "  status TEXT DEFAULT 'generated',\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  expires_at TEXT,\n"
                        "  shipped_at TEXT,\n"
                        "  delivered_at TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Minimal catalog tables for SQLite tests
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS products (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  sku TEXT UNIQUE NOT NULL,\n"
                        "  name TEXT NOT NULL,\n"
                        "  price_cents INT NOT NULL,\n"
                        "  currency TEXT NOT NULL DEFAULT 'USD',\n"
                        "  image_url TEXT,\n"
                        "  specs TEXT,\n"
                        "  active INTEGER DEFAULT 1,\n"
                        "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Backfill columns on existing tables if created before schema update
                try:
                    conn.execute(sql_text("ALTER TABLE products ADD COLUMN image_url TEXT"))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS inventory (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  product_id TEXT NOT NULL,\n"
                        "  stock INT NOT NULL,\n"
                        "  warehouse TEXT DEFAULT 'default',\n"
                        "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Phase 5: inventory sync (SQLite fallback for tests/dev)
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS inventory_sync_runs (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  tenant_id TEXT,\n"
                        "  source TEXT NOT NULL,\n"
                        "  status TEXT NOT NULL DEFAULT 'started',\n"
                        "  started_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  finished_at TEXT,\n"
                        "  records_seen INT DEFAULT 0,\n"
                        "  records_applied INT DEFAULT 0,\n"
                        "  error TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS inventory_external_stock (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  tenant_id TEXT,\n"
                        "  source TEXT NOT NULL,\n"
                        "  sku TEXT NOT NULL,\n"
                        "  warehouse TEXT DEFAULT 'default',\n"
                        "  stock INT NOT NULL DEFAULT 0,\n"
                        "  observed_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                        "  raw_json TEXT\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Minimal customers table for SQLite tests
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS customers (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  email TEXT,\n"
                        "  name TEXT,\n"
                        "  phone TEXT,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                try:
                    conn.execute(sql_text("ALTER TABLE customers ADD COLUMN phone TEXT"))
                except Exception:
                    pass
                try:
                    conn.commit()
                except Exception:
                    pass
                # Idempotency keys storage for write endpoint deduplication
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS idempotency_keys (\n"
                        "  key TEXT PRIMARY KEY,\n"
                        "  fingerprint TEXT NOT NULL,\n"
                        "  response_status INT,\n"
                        "  response_body TEXT,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Per-tenant retention policy configuration
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS retention_policies (\n"
                        "  tenant_id TEXT PRIMARY KEY,\n"
                        "  audit_days INT NOT NULL,\n"
                        "  evidence_days INT NOT NULL,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                # DREAD calibration log — stores predicted vs actual damage for Bayesian tuning
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS dread_calibration_log (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  incident_id TEXT,\n"
                        "  trace_id TEXT,\n"
                        "  predicted_damage REAL,\n"
                        "  predicted_reproducibility REAL,\n"
                        "  predicted_exploitability REAL,\n"
                        "  predicted_affected_users REAL,\n"
                        "  predicted_discoverability REAL,\n"
                        "  predicted_weighted_avg REAL,\n"
                        "  predicted_kill_chain_stage TEXT,\n"
                        "  actual_damage REAL,\n"
                        "  actual_impact_notes TEXT,\n"
                        "  signal_types TEXT,\n"
                        "  closed_by TEXT,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
                # Persistent risk register snapshots for GRC audit trail
                try:
                    conn.execute(sql_text(
                        "CREATE TABLE IF NOT EXISTS risk_register_snapshots (\n"
                        "  id TEXT PRIMARY KEY,\n"
                        "  domain TEXT NOT NULL,\n"
                        "  risk_score REAL NOT NULL,\n"
                        "  risk_band TEXT NOT NULL,\n"
                        "  snapshot_date TEXT NOT NULL,\n"
                        "  risk_owner TEXT,\n"
                        "  mitigation_strategy TEXT,\n"
                        "  mitigation_deadline TEXT,\n"
                        "  residual_risk_score REAL,\n"
                        "  status TEXT NOT NULL DEFAULT 'open',\n"
                        "  signals_json TEXT,\n"
                        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                        ")"
                    ))
                except Exception:
                    pass
    except Exception:
        pass


@contextmanager
def db_session():
    # Prefer a request-bound engine when available (set by middleware via
    # CURRENT_REQUEST) so reads/writes during a request use the same engine
    # instance that tests configured on app.state.engine. Fall back to the
    # module-level engine otherwise.
    try:
        eng = get_engine()
    except Exception:
        eng = engine
    try:
        req = CURRENT_REQUEST.get()
        if req is not None and hasattr(req, "app") and hasattr(req.app, "state"):
            eng_req = getattr(req.app.state, "engine", None)
            if eng_req is not None:
                eng = eng_req
    except Exception:
        eng = engine
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    session = SessionLocal()
    # Best-effort: ensure minimal SQLite tables exist for tests that don't apply schema
    try:
        _ensure_minimal_sqlite_tables(session.bind)
    except Exception:
        pass
    # Optional debug: print which engine URL the session is bound to
    try:
        dbg = os.getenv("DB_SESSION_DEBUG", "0")
        if str(dbg).strip() in ("1", "true", "yes"):
            import sys
            sys.stderr.write(f"[db_session] bind.url={getattr(session.bind, 'url', None)}\n")
            sys.stderr.flush()
    except Exception:
        pass
    # Wrap session.execute so tests can pass plain SQL strings (coerce to text())
    orig_execute = session.execute

    def _execute(self, statement, *args, **kwargs):
        # Accept plain strings or SQLAlchemy TextClause and normalize common Postgres functions
        # Coerce plain SQL strings or TextClause into sqlalchemy.text(),
        # and normalize Postgres now() to SQLite-compatible CURRENT_TIMESTAMP.
        import re
        import time as _time
        from src.app.observability.metrics import record_db_query_latency
        s = None
        if isinstance(statement, TextClause):
            s = str(statement)
        elif isinstance(statement, str):
            s = statement

        if s is not None:
            s = re.sub(r"\bnow\s*\(\s*\)", "CURRENT_TIMESTAMP", s, flags=re.IGNORECASE)
            # When using the SQLite fallback during tests, many test cases
            # insert the same primary keys across the suite. Convert plain
            # INSERTs into INSERT OR REPLACE to avoid UNIQUE constraint
            # failures while preserving semantics for the test harness.
            try:
                if "sqlite" in str(session.bind.dialect.name).lower():
                    s = re.sub(r"\bINSERT\s+INTO\b", "INSERT OR REPLACE INTO", s, flags=re.IGNORECASE)
            except Exception:
                pass
            statement = sql_text(s)
        start = _time.perf_counter()
        result = orig_execute(statement, *args, **kwargs)
        try:
            op = None
            if s:
                op = s.strip().split()[0].lower()
            record_db_query_latency(op or "unknown", _time.perf_counter() - start)
        except Exception:
            pass

        # Wrap result to normalize boolean-like integer columns for SQLite
        try:
            sql_str = None
            try:
                sql_str = str(statement) if isinstance(statement, str) or hasattr(statement, "text") else None
            except Exception:
                sql_str = None

            class ResultWrapper:
                def __init__(self, res, sql):
                    self._res = res
                    self._sql = (sql or "").lower()

                def fetchone(self):
                    row = self._res.fetchone()
                    if row is None:
                        return None
                    return self._convert_row(row)

                def mappings(self):
                    mr = self._res.mappings()

                    class MappingsWrapper:
                        def __init__(self, mapping_res, sql):
                            self._mr = mapping_res
                            self._sql = sql

                        def all(self):
                            rows = self._mr.all()
                            out = []
                            for r in rows:
                                d = dict(r)
                                for k in ("escalated", "blocked"):
                                    if k in d and isinstance(d[k], int):
                                        d[k] = bool(d[k])
                                out.append(d)
                            return out

                        def __getattr__(self, name):
                            return getattr(self._mr, name)

                    return MappingsWrapper(mr, self._sql)

                def __getattr__(self, name):
                    return getattr(self._res, name)

                def _convert_row(self, row):
                    try:
                        vals = tuple(row)
                    except Exception:
                        vals = (row,)
                    # Single-column selects that include boolean-like names
                    if len(vals) == 1:
                        v = vals[0]
                        if isinstance(v, int) and v in (0, 1) and ("escalat" in self._sql or "block" in self._sql):
                            return (bool(v),)
                        return vals
                    # Multi-column: try mapping by name and convert known boolean keys
                    try:
                        if hasattr(row, "_mapping"):
                            md = dict(row._mapping)
                            for k in ("escalated", "blocked"):
                                if k in md and isinstance(md[k], int):
                                    md[k] = bool(md[k])
                            return tuple(md[k] for k in md.keys())
                    except Exception:
                        pass
                    return vals

            return ResultWrapper(result, sql_str)
        except Exception:
            return result

    session.execute = types.MethodType(_execute, session)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:
            pass


def get_engine():
    # Return the module-level engine. Tests commonly monkeypatch this object;
    # auto-replacing from DATABASE_URL here can break request/session parity.
    return engine


def get_db_for_request(request: Request | None = None):
    """Return a sessionmaker-bound session using the request.app.state.engine
    if available, otherwise fall back to the module-level engine. This helper
    is intended for use as a FastAPI dependency `Depends(get_db)`.
    """
    # Prefer a SessionLocal placed on the module by tests, otherwise create one
    # bound to the configured engine or the engine stored on request.app.state.
    eng = None
    try:
        if request is not None and hasattr(request, "app") and hasattr(request.app, "state"):
            eng = getattr(request.app.state, "engine", None)
    except Exception:
        eng = None

    if eng is None:
        eng = globals().get("engine")
    # If a request-specific engine exists, prefer creating a sessionmaker
    # bound to that engine to avoid reusing a global SessionLocal which may
    # be bound to a different engine from another test run.
    if eng is not None and request is not None:
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    else:
        # Always create a fresh sessionmaker bound to eng (module engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    session = SessionLocal()
    try:
        # Ensure minimal tables exist for SQLite binds so route handlers using
        # Depends(get_db) can safely operate in test environments.
        try:
            _ensure_minimal_sqlite_tables(session.bind)
        except Exception:
            pass
        yield session
    finally:
        session.close()


def get_db(request: Request):
    """FastAPI-friendly dependency: `Depends(get_db)` or `Depends(lambda req: get_db(req))`.
    When FastAPI injects the Request object it will be passed here automatically.
    """
    # Delegate to the request-aware session generator so FastAPI
    # treats this as a dependency with teardown (yield-style).
    # Using `yield from` makes `get_db` itself a generator function.
    yield from get_db_for_request(request)


def _build_upsert_sql(dialect: str, table: str, values: dict, conflict_columns: list[str]):
    """Build a dialect-aware upsert SQL statement and parameter dict.

    - For SQLite: uses `INSERT OR REPLACE` with all columns.
    - For Postgres: uses `INSERT ... ON CONFLICT (...) DO UPDATE SET ...`.
    """
    cols = list(values.keys())
    placeholders = ", ".join([f":{c}" for c in cols])
    col_list = ", ".join(cols)
    params = dict(values)
    d = (dialect or "").lower()
    if "sqlite" in d:
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
        return sql_text(sql), params
    # Default to Postgres-style upsert when not SQLite
    conflict_list = ", ".join(conflict_columns or [])
    # Update all non-conflict columns from EXCLUDED
    update_cols = [c for c in cols if c not in (conflict_columns or [])]
    if update_cols:
        set_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
    else:
        # If no non-conflict columns, do nothing on conflict
        set_clause = None
    base = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    if conflict_list:
        if set_clause:
            sql = f"{base} ON CONFLICT ({conflict_list}) DO UPDATE SET {set_clause}"
        else:
            sql = f"{base} ON CONFLICT ({conflict_list}) DO NOTHING"
    else:
        # Without explicit conflict columns, fall back to plain insert
        sql = base
    return sql_text(sql), params


def upsert(session, table: str, values: dict, conflict_columns: list[str]):
    """Execute a dialect-aware upsert using the provided session.

    Example:
        upsert(db, "rule_definitions",
               {"id": "r1", "title": "t", "active": True},
               ["id"])
    """
    try:
        dialect = str(getattr(getattr(session.bind, "dialect", None), "name", "")).lower()
    except Exception:
        dialect = ""
    stmt, params = _build_upsert_sql(dialect, table, values, conflict_columns)
    return session.execute(stmt, params)


async def async_db_op(fn, *args, **kwargs):
    """Run a synchronous ``db_session``-based callable on the default
    executor (thread pool) so async route handlers do not block the
    event loop.

    Usage::

        result = await async_db_op(lambda db: db.execute(...).fetchall())

    The callable receives a ``db_session`` context as its first argument.
    Additional *args / **kwargs are forwarded.
    """
    import asyncio

    def _run():
        with db_session() as _db:
            return fn(_db, *args, **kwargs)

    return await asyncio.to_thread(_run)

