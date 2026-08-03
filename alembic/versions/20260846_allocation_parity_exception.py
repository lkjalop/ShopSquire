"""Add the signed allocation parity exception register.

Revision ID: 20260846_allocation_parity_exception
Revises: 20260845_supplier_sourcing_authority
"""

from alembic import op
import sqlalchemy as sa


revision = "20260846_allocation_parity_exception"
down_revision = "20260845_supplier_sourcing_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allocation_parity_exception",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text()),
        sa.Column("difference_code", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=False),
        sa.Column("signer_id", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("signature_b64", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id", "case_id", "sku", "difference_code", "signature_b64",
            name="uq_allocation_parity_exception_signature",
        ),
        sa.CheckConstraint("length(rationale) >= 12", name="ck_parity_exception_rationale"),
        sa.CheckConstraint("length(evidence_ref) >= 3", name="ck_parity_exception_evidence"),
    )
    op.create_index(
        "ix_allocation_parity_exception_scope",
        "allocation_parity_exception",
        ["tenant_id", "case_id", "expires_at", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_allocation_parity_exception_scope",
        table_name="allocation_parity_exception",
    )
    op.drop_table("allocation_parity_exception")
