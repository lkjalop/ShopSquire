"""SQLite compatibility schema, isolated from request/session ownership.

Production migrations remain authoritative. These ordered compatibility
steps preserve the legacy sparse-test/development schema and its failure
semantics; callers own the connection and collect incomplete work.
"""
from sqlalchemy import text as sql_text


def bootstrap_schema(conn, errors):
    _orders_and_ingress(conn, errors)
    _trace_and_policy(conn, errors)
    _evidence_and_email_security(conn, errors)
    _review_and_decision_audit(conn, errors)
    _playbooks_and_trace_events(conn, errors)
    _customer_and_return_records(conn, errors)
    _catalog_and_inventory(conn, errors)
    _idempotency_and_risk_records(conn, errors)


def _orders_and_ingress(conn, errors):
    conn.execute(sql_text(
        "CREATE TABLE IF NOT EXISTS orders (\n"
        "  id TEXT PRIMARY KEY,\n"
        "  draft_order_id TEXT,\n"
        "  customer_id TEXT,\n"
        "  tenant_id TEXT,\n"
        "  tenant_ownership_status TEXT NOT NULL DEFAULT 'unclassified',\n"
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
        "  tenant_id TEXT,\n"
        "  tenant_ownership_status TEXT NOT NULL DEFAULT 'unclassified',\n"
        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
        ")"
    ))
    conn.execute(sql_text(
        "CREATE TABLE IF NOT EXISTS draft_orders (\n"
        "  id TEXT PRIMARY KEY,\n"
        "  customer_id TEXT,\n"
        "  tenant_id TEXT NOT NULL DEFAULT 'default',\n"
        "  line_items TEXT NOT NULL,\n"
        "  status TEXT NOT NULL DEFAULT 'draft',\n"
        "  version INTEGER NOT NULL DEFAULT 0,\n"
        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
        "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
        ")"
    ))
    try:
        conn.execute(sql_text("ALTER TABLE orders ADD COLUMN guest_email TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # R10.2 STEP 1 (additive, zero behavior change): cart identity becomes
    # (tenant_id, customer_id). DEFAULT 'default' backfills every existing row =
    # exactly today's single-tenant truth; reads/writes get tenant-scoped in the
    # follow-up threading step (docs/SHOPSQUIRE_V2_TENANT_CART_SPEC), never here.
    try:
        conn.execute(sql_text("ALTER TABLE draft_orders ADD COLUMN tenant_id TEXT "
                              "NOT NULL DEFAULT 'default'"))
    except Exception:
        pass   # column already exists (fresh CREATE above includes it)
    try:
        conn.execute(sql_text("ALTER TABLE draft_orders ADD COLUMN version INTEGER "
                              "NOT NULL DEFAULT 0"))
    except Exception:
        pass   # column already exists (fresh CREATE above includes it)
    try:
        conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS ix_draft_orders_tenant_customer_status "
            "ON draft_orders (tenant_id, customer_id, status)"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
        "  tenant_id TEXT NOT NULL DEFAULT 'default',\n"
        "  uid TEXT NOT NULL,\n"
        "  session_id TEXT,\n"
        "  session_epoch TEXT NOT NULL DEFAULT 'legacy',\n"
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


def _trace_and_policy(conn, errors):
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # ── Autonomy-support tables (P2) ──────────────────────────────
    # The moat's data foundation: bounded autonomy needs a full policy/
    # exception/retry/AI-interaction trace + price/inventory history for
    # replay and forecasting. decision_logs (above) is the WHY; these are
    # the policy trace, resilience layer, and forecasting substrate.
    for _ddl in (
        "CREATE TABLE IF NOT EXISTS policy_evaluation_log (\n"
        "  id TEXT PRIMARY KEY, decision_id TEXT, tenant_id TEXT, action TEXT,\n"
        "  value_cents INT, decision TEXT, rule_id TEXT, reason TEXT,\n"
        "  authority TEXT, context TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
        # Canonical schema shared by the authz engine, the resolver, and domain enqueues
        # (market-intel/procurement). MUST carry terminal_outcome + resolved_outcome — the
        # prior schema (domain/kind/payload/outcome) silently broke the authz enqueue.
        "CREATE TABLE IF NOT EXISTS exception_queue (\n"
        "  id TEXT PRIMARY KEY, tenant_id TEXT, domain TEXT, ref_id TEXT,\n"
        "  trace_id TEXT, action TEXT, requester TEXT, terminal_outcome TEXT,\n"
        "  reason TEXT, subject_id TEXT, value_usd REAL, residual TEXT, payload TEXT,\n"
        "  status TEXT DEFAULT 'open', resolved_outcome TEXT,\n"
        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT)",
        "CREATE TABLE IF NOT EXISTS retry_tracking (\n"
        "  id TEXT PRIMARY KEY, ref_id TEXT, operation TEXT, attempts INT DEFAULT 0,\n"
        "  max_attempts INT DEFAULT 3, last_error TEXT, next_attempt TEXT,\n"
        "  status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS ai_interaction_log (\n"
        "  id TEXT PRIMARY KEY, tenant_id TEXT, surface TEXT, model TEXT,\n"
        "  request TEXT, response TEXT, outcome TEXT, latency_ms INT,\n"
        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS price_history (\n"
        "  id TEXT PRIMARY KEY, sku TEXT, price_cents INT, currency TEXT,\n"
        "  source TEXT, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS inventory_level_history (\n"
        "  id TEXT PRIMARY KEY, sku TEXT, warehouse TEXT, stock INT,\n"
        "  recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)",
    ):
        try:
            conn.execute(sql_text(_ddl))
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # Backfill missing domain column for older SQLite files.
    try:
        conn.execute(sql_text("ALTER TABLE rule_definitions ADD COLUMN domain TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)


def _evidence_and_email_security(conn, errors):
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # Ensure ticket_id column exists for older environments
    try:
        conn.execute(sql_text("ALTER TABLE email_security_incidents ADD COLUMN ticket_id TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    for stmt in [
        "ALTER TABLE email_security_incidents ADD COLUMN ground_truth TEXT",
        "ALTER TABLE email_security_incidents ADD COLUMN analyst_verdict TEXT",
        "ALTER TABLE email_security_incidents ADD COLUMN correction_ts TEXT",
        "ALTER TABLE email_security_incidents ADD COLUMN correction_notes TEXT",
    ]:
        try:
            conn.execute(sql_text(stmt))
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(
            sql_text(
                "CREATE TABLE IF NOT EXISTS email_sender_trust (\n"
                "  tenant_id TEXT NOT NULL,\n"
                "  sender_domain_hash TEXT NOT NULL,\n"
                "  first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # SQLite-only compatibility for migration-less unit fixtures.
    # PostgreSQL schema remains Alembic-owned.
    try:
        sender_columns = {
            str(row[1])
            for row in conn.execute(
                sql_text("PRAGMA table_info(email_sender_trust)")
            ).fetchall()
        }
        if "first_seen_at" not in sender_columns:
            conn.execute(
                sql_text(
                    "ALTER TABLE email_sender_trust "
                    "ADD COLUMN first_seen_at TEXT"
                )
            )
        conn.execute(
            sql_text(
                "CREATE TABLE IF NOT EXISTS email_thread_graph_state (\n"
                "  tenant_id TEXT NOT NULL,\n"
                "  thread_key TEXT NOT NULL,\n"
                "  first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                "  last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                "  last_sender_domain TEXT,\n"
                "  sender_domains_json TEXT,\n"
                "  message_count INTEGER NOT NULL DEFAULT 0,\n"
                "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,\n"
                "  PRIMARY KEY (tenant_id, thread_key)\n"
                ")"
            )
        )
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)


def _review_and_decision_audit(conn, errors):
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)
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
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)

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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)

    try:
        conn.execute(sql_text(
            "CREATE TABLE IF NOT EXISTS security_observer_timeseries (\n"
            "  id TEXT PRIMARY KEY,\n"
            "  time TEXT DEFAULT CURRENT_TIMESTAMP,\n"
            "  event_id TEXT,\n"
            "  severity TEXT,\n"
            "  risk_adj REAL,\n"
            "  insider_score REAL,\n"
            "  tenant_id TEXT\n"
            ")"
        ))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # C01: add hash chain columns if missing (migration for existing DBs)
    for stmt in (
        "ALTER TABLE decision_audits ADD COLUMN record_hash TEXT",
        "ALTER TABLE decision_audits ADD COLUMN prev_hash TEXT",
    ):
        try:
            conn.execute(sql_text(stmt))
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)


def _playbooks_and_trace_events(conn, errors):
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_action_exec_idem ON playbook_action_executions(idempotency_key)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_action_dlq_run ON playbook_action_dlq(run_id, step_index)"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_audit_log_chain_created ON audit_log_chain(created_at)"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_runs_trace ON playbook_runs(trace_id)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_runs_playbook ON playbook_runs(playbook_id, playbook_version)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_playbook_run_steps_run ON playbook_run_steps(run_id, step_index)"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # Decision trace events table for observability/testing
    try:
        conn.execute(sql_text(
            "CREATE TABLE IF NOT EXISTS decision_trace_events (\n"
            "  id TEXT PRIMARY KEY,\n"
            "  tenant_id TEXT NOT NULL DEFAULT 'default',\n"
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("ALTER TABLE decision_trace_events ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)


def _customer_and_return_records(conn, errors):
    try:
        conn.execute(sql_text(
            "CREATE TABLE IF NOT EXISTS customers (\n"
            "  id TEXT PRIMARY KEY,\n"
            "  tenant_id TEXT,\n"
            "  tenant_ownership_status TEXT NOT NULL DEFAULT 'unclassified',\n"
            "  email TEXT,\n"
            "  name TEXT,\n"
            "  phone TEXT,\n"
            "  created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
            ")"
        ))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("ALTER TABLE customers ADD COLUMN phone TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # PII encrypted fields (compat; plaintext columns retained for fallback)
    try:
        conn.execute(sql_text("ALTER TABLE orders ADD COLUMN guest_email_hash TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("ALTER TABLE orders ADD COLUMN guest_email_encrypted TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    for _stmt in (
        "ALTER TABLE orders ADD COLUMN tenant_id TEXT",
        "ALTER TABLE orders ADD COLUMN tenant_ownership_status TEXT NOT NULL DEFAULT 'unclassified'",
        "ALTER TABLE order_sessions ADD COLUMN tenant_id TEXT",
        "ALTER TABLE order_sessions ADD COLUMN tenant_ownership_status TEXT NOT NULL DEFAULT 'unclassified'",
        "ALTER TABLE customers ADD COLUMN tenant_id TEXT",
        "ALTER TABLE customers ADD COLUMN tenant_ownership_status TEXT NOT NULL DEFAULT 'unclassified'",
        "ALTER TABLE orders ADD COLUMN stripe_intent_id TEXT",
        "ALTER TABLE orders ADD COLUMN tracking_number TEXT",
        "ALTER TABLE orders ADD COLUMN carrier TEXT",
        # attribution (E1): link an order back to the recommendation decision.
        "ALTER TABLE orders ADD COLUMN trace_id TEXT",
        "ALTER TABLE orders ADD COLUMN decision_id TEXT",
    ):
        try:
            conn.execute(sql_text(_stmt))
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_orders_stripe_intent ON orders(stripe_intent_id)"
        ))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("ALTER TABLE customers ADD COLUMN email_hash TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("ALTER TABLE customers ADD COLUMN email_encrypted TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("ALTER TABLE customers ADD COLUMN phone_encrypted TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # Ensure PII columns exist on cases table (added after creation)
    try:
        conn.execute(sql_text("ALTER TABLE cases ADD COLUMN guest_email_hash TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.execute(sql_text("ALTER TABLE cases ADD COLUMN guest_email_encrypted TEXT"))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)


def _catalog_and_inventory(conn, errors):
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
            "  product_type TEXT,\n"
            "  brand TEXT,\n"
            "  category TEXT,\n"
            "  attributes TEXT,\n"
            "  active INTEGER DEFAULT 1,\n"
            "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
            ")"
        ))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    # Backfill columns on existing tables if created before schema update.
    # product_type/brand/category/attributes are the agnostic-core keystone
    # (the brand/category cols candidate_retriever + upsell already SELECT).
    for _col, _type in (
        ("image_url", "TEXT"), ("product_type", "TEXT"), ("brand", "TEXT"),
        ("category", "TEXT"), ("attributes", "TEXT"),
    ):
        try:
            conn.execute(sql_text(f"ALTER TABLE products ADD COLUMN {_col} {_type}"))
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
            "  heartbeat_at TEXT,\n"
            "  budget_deadline_at TEXT,\n"
            "  outcome_type TEXT,\n"
            "  records_seen INT DEFAULT 0,\n"
            "  records_applied INT DEFAULT 0,\n"
            "  error TEXT\n"
            ")"
        ))
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    for _sync_col, _sync_type in (
        ("heartbeat_at", "TEXT"),
        ("budget_deadline_at", "TEXT"),
        ("outcome_type", "TEXT"),
    ):
        try:
            conn.execute(
                sql_text(
                    f"ALTER TABLE inventory_sync_runs "
                    f"ADD COLUMN {_sync_col} {_sync_type}"
                )
            )
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    try:
        conn.commit()
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)


def _idempotency_and_risk_records(conn, errors):
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
    for statement in (
        "ALTER TABLE idempotency_keys ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE idempotency_keys ADD COLUMN response_status INT",
        "ALTER TABLE idempotency_keys ADD COLUMN response_body TEXT",
        # M2 lease/reclaim columns
        "ALTER TABLE idempotency_keys ADD COLUMN owner_token TEXT",
        "ALTER TABLE idempotency_keys ADD COLUMN lease_expires_at REAL",
        "ALTER TABLE idempotency_keys ADD COLUMN updated_at TEXT",
    ):
        try:
            conn.execute(sql_text(statement))
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
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
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            errors.append(type(exc).__name__)
