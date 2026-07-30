"""Add durable, tenant-scoped privacy deletion orchestration.

Revision ID: 20260830_privacy_deletion_jobs
Revises: 20260829_tenant_chat_messages
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830_privacy_deletion_jobs"
down_revision = "20260829_tenant_chat_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "privacy_deletion_job" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "privacy_deletion_job",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("subject_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stages_json", sa.Text(), nullable=False),
        sa.Column("action_required_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','completed','action_required','failed')",
            name="ck_privacy_deletion_job_status",
        ),
    )
    op.create_index(
        "ix_privacy_deletion_tenant_subject",
        "privacy_deletion_job",
        ["tenant_id", "subject_hash", "created_at"],
    )


def downgrade() -> None:
    # Privacy audit evidence must survive an application rollback.
    return
