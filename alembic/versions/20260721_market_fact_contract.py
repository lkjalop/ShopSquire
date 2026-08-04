"""Canonical market history, ATP, and marketing fact families.

Revision ID: 20260721_market_fact_contract
Revises: 20260720_product_embeddings_reconcile
"""
from alembic import op


revision = "20260721_market_fact_contract"
down_revision = "20260720_product_embeddings_reconcile"
branch_labels = None
depends_on = None


TABLE_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS trend_indicator (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL DEFAULT 'default',
        entity_ref TEXT, indicator_type TEXT, direction TEXT, value REAL, baseline REAL,
        confidence REAL, observed_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS competitor_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL DEFAULT 'default',
        entity_ref TEXT, our_price_cents INTEGER, competitor_price_cents INTEGER,
        competitor TEXT, observed_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS offer_policy (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL DEFAULT 'default',
        entity_ref TEXT, action TEXT, discount_pct REAL, floor_margin_pct REAL,
        rationale TEXT, decided_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS market_signal_rollup (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default', bucket_date TEXT,
        signal_type TEXT, source TEXT, signal_count INTEGER, trust_sum REAL, trust_avg REAL,
        last_occurred_at TEXT, updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS inventory_atp_fact (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1,
        deduplication_id TEXT NOT NULL, material_id TEXT, sku TEXT, variant_id TEXT,
        taxonomy_node TEXT, location_id TEXT, requested_quantity INTEGER, requested_date TEXT,
        on_hand_quantity INTEGER, committed_quantity INTEGER, incoming_receipts_quantity INTEGER,
        safety_stock_quantity INTEGER, lead_time_days REAL, confirmed_quantity INTEGER,
        confirmed_date TEXT, supplier_id TEXT, source_system TEXT NOT NULL,
        source_record_id TEXT, provenance_json TEXT, confidence REAL,
        observed_at TEXT NOT NULL, ingested_at TEXT NOT NULL, valid_from TEXT, valid_to TEXT,
        freshness_policy TEXT, status TEXT NOT NULL DEFAULT 'active')""",
    """CREATE TABLE IF NOT EXISTS marketing_event_fact (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1,
        deduplication_id TEXT NOT NULL, event_type TEXT NOT NULL, subject_hash TEXT,
        session_id TEXT, sku TEXT, variant_id TEXT, taxonomy_node TEXT, campaign_id TEXT,
        creative_id TEXT, channel TEXT, value REAL, currency TEXT, quantity INTEGER,
        consent_state TEXT, attribution_window TEXT, source_system TEXT NOT NULL,
        source_record_id TEXT, provenance_json TEXT, confidence REAL,
        occurred_at TEXT NOT NULL, ingested_at TEXT NOT NULL, valid_from TEXT, valid_to TEXT,
        freshness_policy TEXT, status TEXT NOT NULL DEFAULT 'active')""",
)

INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_ti_entity ON trend_indicator(tenant_id, entity_ref, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_cs_entity ON competitor_snapshot(tenant_id, entity_ref, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_op_entity ON offer_policy(tenant_id, entity_ref, decided_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_msr_bucket ON market_signal_rollup(tenant_id, bucket_date, signal_type, source)",
    "CREATE INDEX IF NOT EXISTS ix_msr_date ON market_signal_rollup(bucket_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_atp_fact_dedup ON inventory_atp_fact(tenant_id, deduplication_id)",
    "CREATE INDEX IF NOT EXISTS ix_atp_fact_subject ON inventory_atp_fact(tenant_id, sku, location_id, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_atp_fact_taxonomy ON inventory_atp_fact(tenant_id, taxonomy_node, observed_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_marketing_fact_dedup ON marketing_event_fact(tenant_id, deduplication_id)",
    "CREATE INDEX IF NOT EXISTS ix_marketing_fact_funnel ON marketing_event_fact(tenant_id, event_type, occurred_at)",
    "CREATE INDEX IF NOT EXISTS ix_marketing_fact_campaign ON marketing_event_fact(tenant_id, campaign_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS ix_marketing_fact_subject ON marketing_event_fact(tenant_id, sku, taxonomy_node, occurred_at)",
)


def upgrade() -> None:
    dialect = str(getattr(op.get_bind().dialect, "name", "")).lower()
    for statement in TABLE_STATEMENTS:
        if "postgres" in dialect:
            statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                          "BIGSERIAL PRIMARY KEY")
        op.execute(statement)
    for statement in INDEX_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in ("marketing_event_fact", "inventory_atp_fact", "market_signal_rollup",
                  "offer_policy", "competitor_snapshot", "trend_indicator"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
