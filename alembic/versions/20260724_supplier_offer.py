"""Tenant-scoped material/vendor cost offers with explicit provenance.

Revision ID: 20260724_supplier_offer
Revises: 20260723_market_fact_quarantine_dedup
"""
from alembic import op


revision = "20260724_supplier_offer"
down_revision = "20260723_market_fact_quarantine_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_offer (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
            sku TEXT NOT NULL, cost_kind TEXT NOT NULL,
            purchase_unit_cost_cents INTEGER NOT NULL, freight_unit_cents INTEGER DEFAULT 0,
            duty_unit_cents INTEGER DEFAULT 0, handling_unit_cents INTEGER DEFAULT 0,
            landed_unit_cost_cents INTEGER NOT NULL, currency TEXT NOT NULL,
            tax_basis TEXT NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
            source_system TEXT NOT NULL, source_record_id TEXT NOT NULL,
            provenance_json TEXT NOT NULL, confidence REAL NOT NULL,
            simulation_only INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, supplier_id, sku, source_record_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_offer_lookup
        ON supplier_offer(tenant_id, sku, currency, status, effective_from)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS supplier_offer")
