"""Add rebuildable inventory projections and governed UoM conversions.

Revision ID: 20260820_inventory_projection
Revises: 20260819_party_timeline
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_inventory_projection"
down_revision = "20260819_party_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "uom_conversion_authority" not in tables:
        op.create_table(
            "uom_conversion_authority",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("from_code", sa.Text(), nullable=False),
            sa.Column("to_code", sa.Text(), nullable=False),
            sa.Column("factor", sa.Text(), nullable=False),
            sa.Column("rounding_mode", sa.Text(), nullable=False),
            sa.Column("rounding_increment", sa.Text()),
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("effective_to", sa.DateTime(timezone=True)),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("source_record_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("approved_by", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "from_code"],
                ["uom_unit.tenant_id", "uom_unit.code"],
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "to_code"],
                ["uom_unit.tenant_id", "uom_unit.code"],
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "from_code",
                "to_code",
                "effective_from",
                "source",
                "source_record_id",
                name="uq_uom_conversion_revision",
            ),
        )
        op.create_index(
            "ix_uom_conversion_effective",
            "uom_conversion_authority",
            ["tenant_id", "from_code", "to_code", "status", "effective_from"],
        )
    if "inventory_projection_run" not in tables:
        op.create_table(
            "inventory_projection_run",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("projection_version", sa.Integer(), nullable=False),
            sa.Column("input_count", sa.Integer(), nullable=False),
            sa.Column("projection_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "source",
                "projection_hash",
                name="uq_inventory_projection_rebuild",
            ),
        )
        op.create_index(
            "ix_inventory_projection_run_scope",
            "inventory_projection_run",
            ["tenant_id", "source", "finished_at"],
        )
    if "inventory_projection_balance" not in tables:
        op.create_table(
            "inventory_projection_balance",
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("variant_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("uom", sa.Text(), nullable=False),
            sa.Column("custody", sa.Text(), nullable=False),
            sa.Column("quantity", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("projection_run_id", sa.String(64), nullable=False),
            sa.ForeignKeyConstraint(
                ["projection_run_id"],
                ["inventory_projection_run.id"],
            ),
            sa.PrimaryKeyConstraint(
                "tenant_id",
                "source",
                "variant_id",
                "location_id",
                "uom",
                "custody",
                name="pk_inventory_projection_balance",
            ),
        )
        op.create_index(
            "ix_inventory_projection_balance_lookup",
            "inventory_projection_balance",
            ["tenant_id", "variant_id", "location_id", "status"],
        )
    if "inventory_projection_exception" not in tables:
        op.create_table(
            "inventory_projection_exception",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("projection_run_id", sa.String(64), nullable=False),
            sa.Column("exception_type", sa.Text(), nullable=False),
            sa.Column("observation_id", sa.String(64)),
            sa.Column("details_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["projection_run_id"],
                ["inventory_projection_run.id"],
            ),
        )
        op.create_index(
            "ix_inventory_projection_exception_scope",
            "inventory_projection_exception",
            ["tenant_id", "source", "exception_type"],
        )


def downgrade() -> None:
    # Projection rows are disposable, but conversion approvals are authority
    # records. Retain both to avoid silently destroying audit evidence.
    return
