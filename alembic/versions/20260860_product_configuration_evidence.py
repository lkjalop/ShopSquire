"""Add exact product configuration and evidence observations.

Revision ID: 20260860_product_evidence
Revises: 20260859_search_demand
"""
from alembic import op
import sqlalchemy as sa


revision = "20260860_product_evidence"
down_revision = "20260859_search_demand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Local demo databases may have these tables already because older startup
    # code called ``Base.metadata.create_all`` before Alembic owned the schema.
    # Adopt only a complete, structurally compatible set; partial or mismatched
    # state fails loudly instead of pretending the migration succeeded.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    required_columns = {
        "product_configurations": {
            "id", "tenant_id", "product_id", "sku", "title", "configuration_hash",
            "form_factor", "mobility", "device_class", "price_cents", "currency",
        },
        "product_evidence_observations": {
            "id", "configuration_id", "attribute_key", "value_json", "claim_class",
            "evidence_status", "source_id", "source_record_id", "observed_at",
        },
        "product_availability_observations": {
            "id", "configuration_id", "location_id", "status", "source_record_id",
            "observed_at",
        },
        "shopping_cases": {"id", "case_id", "tenant_id", "uid", "status"},
        "requirement_proposals": {
            "id", "proposal_id", "case_id", "tenant_id", "uid", "version", "status",
            "source_reference", "claims_json",
        },
    }
    existing = set(inspector.get_table_names()) & set(required_columns)
    if existing:
        if existing != set(required_columns):
            missing = sorted(set(required_columns) - existing)
            raise RuntimeError(
                "partial pre-Alembic product-evidence schema; missing tables: "
                + ", ".join(missing)
            )
        for table_name, required in required_columns.items():
            actual = {column["name"] for column in inspector.get_columns(table_name)}
            missing_columns = sorted(required - actual)
            if missing_columns:
                raise RuntimeError(
                    f"incompatible pre-Alembic table {table_name}; missing columns: "
                    + ", ".join(missing_columns)
                )
        required_indexes = {
            "product_configurations": (
                "ix_product_configuration_mpn", ["tenant_id", "mpn"],
            ),
            "product_evidence_observations": (
                "ix_product_evidence_attribute", ["configuration_id", "attribute_key"],
            ),
            "product_availability_observations": (
                "ix_product_availability_location",
                ["configuration_id", "location_id", "observed_at"],
            ),
            "requirement_proposals": (
                "ix_requirement_proposal_case", ["tenant_id", "case_id", "status"],
            ),
        }
        for table_name, (index_name, columns) in required_indexes.items():
            names = {row["name"] for row in inspector.get_indexes(table_name)}
            if index_name not in names:
                op.create_index(index_name, table_name, columns)
        return

    op.create_table(
        "product_configurations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("product_id", sa.Text(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("manufacturer", sa.Text()),
        sa.Column("mpn", sa.Text()),
        sa.Column("retailer_sku", sa.Text()),
        sa.Column("retailer", sa.Text()),
        sa.Column("source_url", sa.Text()),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("form_factor", sa.Text(), nullable=False),
        sa.Column("mobility", sa.Text(), nullable=False),
        sa.Column("device_class", sa.Text(), nullable=False),
        sa.Column("os_edition", sa.Text()),
        sa.Column("gpu_class", sa.Text()),
        sa.Column("gpu_vram_gb", sa.Integer()),
        sa.Column("gpu_tgp_w", sa.Integer()),
        sa.Column("ram_installed_gb", sa.Integer()),
        sa.Column("ram_ceiling_gb", sa.Integer()),
        sa.Column("ram_upgradeable", sa.Boolean()),
        sa.Column("storage_gb", sa.Integer()),
        sa.Column("warranty_type", sa.Text()),
        sa.Column("warranty_years", sa.Integer()),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("specification_observed_at", sa.DateTime()),
        sa.Column("price_observed_at", sa.DateTime()),
        sa.Column("availability_observed_at", sa.DateTime()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("tenant_id", "sku", "configuration_hash", name="uq_product_configuration"),
    )
    op.create_index("ix_product_configuration_mpn", "product_configurations", ["tenant_id", "mpn"])
    op.create_table(
        "product_evidence_observations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("configuration_id", sa.Text(), sa.ForeignKey("product_configurations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attribute_key", sa.Text(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("unit", sa.Text()),
        sa.Column("claim_class", sa.Text(), nullable=False),
        sa.Column("evidence_status", sa.Text(), nullable=False),
        sa.Column("conflict_group", sa.Text()),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("source_excerpt", sa.Text()),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("supersedes_id", sa.Text(), sa.ForeignKey("product_evidence_observations.id")),
    )
    op.create_index("ix_product_evidence_attribute", "product_evidence_observations", ["configuration_id", "attribute_key"])
    op.create_table(
        "product_availability_observations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("configuration_id", sa.Text(), sa.ForeignKey("product_configurations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer()),
        sa.Column("lead_time_min_days", sa.Integer()),
        sa.Column("lead_time_max_days", sa.Integer()),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
    )
    op.create_index("ix_product_availability_location", "product_availability_observations", ["configuration_id", "location_id", "observed_at"])
    op.create_table(
        "shopping_cases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("retained_purpose", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("tenant_id", "case_id", name="uq_shopping_case_tenant"),
    )
    op.create_table(
        "requirement_proposals",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("claims_json", sa.JSON(), nullable=False),
        sa.Column("acceptance_json", sa.JSON()),
        sa.Column("acceptance_idempotency_key", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("tenant_id", "proposal_id", name="uq_requirement_proposal_tenant"),
    )
    op.create_index("ix_requirement_proposal_case", "requirement_proposals", ["tenant_id", "case_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_requirement_proposal_case", table_name="requirement_proposals")
    op.drop_table("requirement_proposals")
    op.drop_table("shopping_cases")
    op.drop_index("ix_product_availability_location", table_name="product_availability_observations")
    op.drop_table("product_availability_observations")
    op.drop_index("ix_product_evidence_attribute", table_name="product_evidence_observations")
    op.drop_table("product_evidence_observations")
    op.drop_index("ix_product_configuration_mpn", table_name="product_configurations")
    op.drop_table("product_configurations")
