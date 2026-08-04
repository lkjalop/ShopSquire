"""Add versioned business semantics, currency/UoM authority and governed evidence.

Revision ID: 20260813_canonical_semantics
Revises: 20260812_communication_observations
"""
from alembic import op
import sqlalchemy as sa


revision = "20260813_canonical_semantics"
down_revision = "20260812_communication_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "authoritative_business_observation" in tables:
        columns = {column["name"] for column in inspector.get_columns("authoritative_business_observation")}
        additions = (
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("event_kind", sa.Text(), nullable=False, server_default="observation"),
            sa.Column("corrects_observation_id", sa.String(64)),
            sa.Column("reverses_observation_id", sa.String(64)),
        )
        for column in additions:
            name = str(column.name)
            if name not in columns:
                op.add_column("authoritative_business_observation", column)

    if "currency_rate_authority" not in tables:
        op.create_table(
            "currency_rate_authority",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("base_currency", sa.String(3), nullable=False),
            sa.Column("quote_currency", sa.String(3), nullable=False),
            sa.Column("rate_decimal", sa.Text(), nullable=False),
            sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("source_record_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="approved"),
            sa.Column("approved_by", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "base_currency", "quote_currency", "as_of", "source", name="uq_fx_authority_quote"),
        )
    if "uom_category" not in tables:
        op.create_table(
            "uom_category",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.UniqueConstraint("tenant_id", "name", name="uq_uom_category_name"),
        )
    if "uom_unit" not in tables:
        op.create_table(
            "uom_unit",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("category_id", sa.Text(), nullable=False),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("factor_to_base", sa.Text(), nullable=False),
            sa.Column("is_base", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["category_id"], ["uom_category.id"]),
            sa.UniqueConstraint("tenant_id", "code", name="uq_uom_unit_code"),
        )
    if "product_variant_identity" not in tables:
        op.create_table(
            "product_variant_identity",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("template_id", sa.Text(), nullable=False),
            sa.Column("variant_id", sa.Text(), nullable=False),
            sa.Column("sku", sa.Text(), nullable=False),
            sa.Column("base_uom_code", sa.Text(), nullable=False),
            sa.Column("attributes_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("tenant_id", "variant_id", name="uq_product_variant_id"),
            sa.UniqueConstraint("tenant_id", "sku", name="uq_product_variant_sku"),
        )
    if "supplier_score_shadow" not in tables:
        op.create_table(
            "supplier_score_shadow",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("supplier_id", sa.Text(), nullable=False),
            sa.Column("model_version", sa.Text(), nullable=False),
            sa.Column("score", sa.Float()),
            sa.Column("sample_size", sa.Integer(), nullable=False),
            sa.Column("confidence_low", sa.Float()),
            sa.Column("confidence_high", sa.Float()),
            sa.Column("components_json", sa.Text(), nullable=False),
            sa.Column("outcome_json", sa.Text()),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_supplier_score_shadow_scope", "supplier_score_shadow", ["tenant_id", "supplier_id", "created_at"])
    if "market_source_policy" not in tables:
        op.create_table(
            "market_source_policy",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source_system", sa.Text(), nullable=False),
            sa.Column("trust_tier", sa.Text(), nullable=False),
            sa.Column("licence_id", sa.Text(), nullable=False),
            sa.Column("licence_url", sa.Text(), nullable=False),
            sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("terms_hash", sa.String(64), nullable=False),
            sa.Column("allowed_uses_json", sa.Text(), nullable=False),
            sa.Column("personal_data_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("approved_by", sa.Text(), nullable=False),
            sa.UniqueConstraint("tenant_id", "source_system", name="uq_market_source_policy"),
        )
    if "relevance_label_seal" not in tables:
        op.create_table(
            "relevance_label_seal",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("corpus_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("reviewer", sa.Text(), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attestation", sa.Text(), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    # Audit, financial-authority and human-review records are intentionally retained.
    return
