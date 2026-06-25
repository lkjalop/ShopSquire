"""Market-intelligence & adaptive-growth tables → Alembic (prod-parity for the runtime-ensured set).

Eleven tables backing the adaptive-growth subsystem are created at runtime via ensure_table() /
CREATE TABLE IF NOT EXISTS in their service modules (works on Postgres + SQLite alike). This migration
brings them under version control so prod schema is explicit and reviewable — without changing
behaviour: the DDL is byte-for-byte the same CREATE TABLE / CREATE INDEX IF NOT EXISTS the services
emit, so it is fully idempotent and safe whether the tables were already runtime-created or not.

Tables: market_signal, market_finding, human_feedback, shadow_action, contact_consent, contact_event,
contact_audit, experiment_ops_heartbeat, experiment_run, experiment_assignment, experiment_result.

The statement lists are module-level so a unit test can apply them to a fresh SQLite engine and assert
the tables exist (and that a second apply is a no-op) without an alembic op context.
"""
from alembic import op

# revision identifiers
revision = "20260626_market_autonomy"
down_revision = "20260625_attribution"
branch_labels = None
depends_on = None


# CREATE TABLE IF NOT EXISTS — copied verbatim from each service's _DDL (single source of truth).
TABLE_STATEMENTS = (
    # market_signal — src/app/services/market_signal.py
    """
    CREATE TABLE IF NOT EXISTS market_signal (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        schema_version INTEGER DEFAULT 1,
        signal_type TEXT,
        source TEXT,
        dedup_key TEXT,
        trust_score REAL,
        payload_json TEXT,
        occurred_at TEXT,
        ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # market_finding — src/app/services/market_analysis.py
    """
    CREATE TABLE IF NOT EXISTS market_finding (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        schema_version INTEGER DEFAULT 1,
        finding_type TEXT,
        entity_ref TEXT,
        severity TEXT,
        confidence REAL,
        summary TEXT,
        evidence_json TEXT,
        window TEXT,
        dedup_key TEXT,
        status TEXT DEFAULT 'active',
        corrected_by_human INTEGER DEFAULT 0,
        correction_note TEXT,
        superseded_by TEXT,
        detected_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # human_feedback — src/app/services/human_feedback.py
    """
    CREATE TABLE IF NOT EXISTS human_feedback (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        schema_version INTEGER DEFAULT 1,
        feedback_type TEXT,
        subject_hash TEXT,
        entity_ref TEXT,
        polarity REAL,
        weight REAL,
        source TEXT,
        dedup_key TEXT,
        occurred_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # shadow_action — src/app/services/shadow_actions.py
    """
    CREATE TABLE IF NOT EXISTS shadow_action (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        schema_version INTEGER DEFAULT 1,
        action_type TEXT,
        target_ref TEXT,
        source_finding_type TEXT,
        direction TEXT,
        magnitude REAL,
        confidence REAL,
        rationale TEXT,
        params_json TEXT,
        status TEXT DEFAULT 'proposed',
        dedup_key TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # contact_consent / contact_event / contact_audit — src/app/services/contact_governance.py
    """
    CREATE TABLE IF NOT EXISTS contact_consent (
        tenant_id TEXT DEFAULT 'default',
        uid_hash TEXT,
        channel TEXT,
        granted INTEGER DEFAULT 0,
        region TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (tenant_id, uid_hash, channel)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contact_event (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        uid_hash TEXT,
        channel TEXT,
        campaign_id TEXT,
        sent_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contact_audit (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        uid_hash TEXT,
        channel TEXT,
        campaign_id TEXT,
        decision TEXT,
        reason TEXT,
        region TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # experiment_ops_heartbeat — src/app/services/experiment_ops.py
    """
    CREATE TABLE IF NOT EXISTS experiment_ops_heartbeat (
        name TEXT PRIMARY KEY,
        beat_at TEXT
    )
    """,
    # experiment_run / experiment_assignment / experiment_result — src/app/services/experiments.py
    """
    CREATE TABLE IF NOT EXISTS experiment_run (
        id TEXT PRIMARY KEY, name TEXT, target_metric TEXT, status TEXT DEFAULT 'draft',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experiment_assignment (
        id TEXT PRIMARY KEY, experiment_id TEXT, subject_hash TEXT, variant TEXT,
        assigned_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experiment_result (
        id TEXT PRIMARY KEY, experiment_id TEXT, variant TEXT, decision TEXT,
        uplift_pct REAL, evidence_json TEXT, decided_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)

# CREATE [UNIQUE] INDEX IF NOT EXISTS — copied verbatim from each service.
INDEX_STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_market_signal_dedup ON market_signal(tenant_id, dedup_key)",
    "CREATE INDEX IF NOT EXISTS ix_market_signal_type ON market_signal(signal_type)",
    "CREATE INDEX IF NOT EXISTS ix_market_signal_source ON market_signal(source)",
    "CREATE INDEX IF NOT EXISTS ix_market_signal_occurred ON market_signal(occurred_at)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_type ON market_finding(finding_type)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_detected ON market_finding(detected_at)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_dedup ON market_finding(tenant_id, dedup_key, status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_human_feedback_dedup ON human_feedback(tenant_id, dedup_key)",
    "CREATE INDEX IF NOT EXISTS ix_human_feedback_type ON human_feedback(feedback_type)",
    "CREATE INDEX IF NOT EXISTS ix_human_feedback_entity ON human_feedback(entity_ref)",
    "CREATE INDEX IF NOT EXISTS ix_shadow_action_type ON shadow_action(action_type)",
    "CREATE INDEX IF NOT EXISTS ix_shadow_action_dedup ON shadow_action(tenant_id, dedup_key, status)",
    "CREATE INDEX IF NOT EXISTS ix_contact_event_lookup ON contact_event(tenant_id, uid_hash, channel, sent_at)",
    "CREATE INDEX IF NOT EXISTS ix_contact_event_campaign ON contact_event(tenant_id, uid_hash, campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_contact_audit_uid ON contact_audit(tenant_id, uid_hash, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_expasn_subject ON experiment_assignment(experiment_id, subject_hash)",
    "CREATE INDEX IF NOT EXISTS ix_expresult_exp ON experiment_result(experiment_id)",
)

# Drop order: indexes implicitly drop with their tables on both PG and SQLite, so dropping the tables
# is sufficient. Reverse of creation just for tidiness.
_DROP_TABLES = (
    "experiment_result", "experiment_assignment", "experiment_run", "experiment_ops_heartbeat",
    "contact_audit", "contact_event", "contact_consent", "shadow_action", "human_feedback",
    "market_finding", "market_signal",
)


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
