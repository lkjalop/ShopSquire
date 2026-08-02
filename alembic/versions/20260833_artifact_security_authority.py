"""Append-only artifact verdicts and exact decision bindings.

Revision ID: 20260833_artifact_security_authority
Revises: 20260832_ragas_baseline_schema_alignment
"""
from alembic import op
import sqlalchemy as sa

revision = "20260833_artifact_security_authority"
down_revision = "20260832_ragas_baseline_schema_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_security_verdicts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text()),
        sa.Column("artifact_sha256", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("verdict_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("supersedes_verdict_id", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "artifact_id", "verdict_version", name="uq_artifact_verdict_version"),
        sa.CheckConstraint("state IN ('received','admitted','pending','clean','quarantined','degraded','superseded')", name="ck_artifact_verdict_state"),
    )
    op.create_index("ix_artifact_verdict_current", "artifact_security_verdicts", ["tenant_id", "artifact_id", "verdict_version"])
    op.create_table(
        "artifact_decision_bindings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.Text(), nullable=False),
        sa.Column("verdict_id", sa.Text(), nullable=False),
        sa.Column("verdict_version", sa.Integer(), nullable=False),
        sa.Column("decision_kind", sa.Text(), nullable=False),
        sa.Column("decision_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("invalidated_at", sa.Text()),
        sa.Column("invalidation_reason", sa.Text()),
        sa.UniqueConstraint("tenant_id", "artifact_id", "decision_kind", "decision_id", name="uq_artifact_decision_binding"),
    )
    op.create_index("ix_artifact_binding_decision", "artifact_decision_bindings", ["tenant_id", "decision_kind", "decision_id"])
    op.create_table(
        "artifact_security_incidents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("artifact_security_incidents")
    op.drop_index("ix_artifact_binding_decision", table_name="artifact_decision_bindings")
    op.drop_table("artifact_decision_bindings")
    op.drop_index("ix_artifact_verdict_current", table_name="artifact_security_verdicts")
    op.drop_table("artifact_security_verdicts")
