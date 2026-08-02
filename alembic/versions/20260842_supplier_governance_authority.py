"""Move supplier governance profiles under migration authority.

Revision ID: 20260842_supplier_governance_authority
Revises: 20260841_procurement_orchestration
"""

from alembic import op
import sqlalchemy as sa


revision = "20260842_supplier_governance_authority"
down_revision = "20260841_procurement_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "supplier_governance_profiles" in inspector.get_table_names():
        return
    op.create_table(
        "supplier_governance_profiles",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("supplier_key", sa.Text(), nullable=False),
        sa.Column("vendor_name", sa.Text()),
        sa.Column("approved_domains_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("observed_domains_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("approved_contacts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("observed_contacts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("approved_bank_fingerprints_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("observed_bank_fingerprints_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("trusted_template_hashes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("observed_template_hashes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("pending_updates_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("history_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("notes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("tenant_id", "supplier_key"),
    )


def downgrade() -> None:
    op.drop_table("supplier_governance_profiles")
