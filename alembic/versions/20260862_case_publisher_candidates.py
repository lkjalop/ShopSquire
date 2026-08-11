"""Persist case-bound open-world publisher candidates.

Revision ID: 20260862_case_publishers
Revises: 20260861_case_fulfillment
"""
from alembic import op
import sqlalchemy as sa


revision = "20260862_case_publishers"
down_revision = "20260861_case_fulfillment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_case_publisher_candidates",
        sa.Column("candidate_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("query_axes_json", sa.JSON(), nullable=False),
        sa.Column("discovery_receipt_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("authority_status", sa.Text(), nullable=False),
        sa.Column("approval_scope", sa.Text(), nullable=True),
        sa.Column("allowed_claim_types_json", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approval_idempotency_key", sa.Text(), nullable=True),
        sa.Column("requirement_proposal_id", sa.Text(), nullable=True),
        sa.Column("research_result_json", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "case_id", "url", name="uq_case_publisher_candidate_url",
        ),
    )
    op.create_index(
        "ix_case_publisher_candidate_owner",
        "shopping_case_publisher_candidates",
        ["tenant_id", "case_id", "uid", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_case_publisher_candidate_owner",
        table_name="shopping_case_publisher_candidates",
    )
    op.drop_table("shopping_case_publisher_candidates")
