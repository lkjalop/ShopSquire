"""Persist authenticated operator-to-tenant membership.

Revision ID: 20260805_operator_membership
Revises: 20260804_inventory_claims
"""
from alembic import op
import sqlalchemy as sa


revision = "20260805_operator_membership"
down_revision = "20260804_inventory_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "operator_tenant_membership" not in tables:
        op.create_table(
            "operator_tenant_membership",
            sa.Column("principal_hash", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("role", sa.String(64), nullable=False),
            sa.Column("subject_id", sa.String(255)),
            sa.Column("auth_method", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.PrimaryKeyConstraint(
                "principal_hash",
                "tenant_id",
                name="pk_operator_tenant_membership",
            ),
        )
        op.create_index(
            "ix_operator_tenant_membership_tenant",
            "operator_tenant_membership",
            ["tenant_id", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "operator_tenant_membership" in set(sa.inspect(bind).get_table_names()):
        op.drop_index(
            "ix_operator_tenant_membership_tenant",
            table_name="operator_tenant_membership",
        )
        op.drop_table("operator_tenant_membership")
