"""Complete the migration-owned exception queue schema.

Revision ID: 20260854_exception_queue
Revises: 20260853_conversation_case
"""

from alembic import op
import sqlalchemy as sa


revision = "20260854_exception_queue"
down_revision = "20260853_conversation_case"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("exception_queue")}
    additions = (
        ("tenant_id", sa.Text()),
        ("domain", sa.Text()),
        ("ref_id", sa.Text()),
        ("payload", sa.Text()),
    )
    for name, column_type in additions:
        if name not in existing:
            op.add_column("exception_queue", sa.Column(name, column_type, nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("exception_queue")}
    if "ix_exception_queue_tenant_status" not in indexes:
        op.create_index(
            "ix_exception_queue_tenant_status",
            "exception_queue",
            ["tenant_id", "status", "created_at"],
        )
    if "ix_exception_queue_domain_ref" not in indexes:
        op.create_index(
            "ix_exception_queue_domain_ref",
            "exception_queue",
            ["tenant_id", "domain", "ref_id"],
        )


def downgrade() -> None:
    # Exception identity and audit payloads are retained across code rollback.
    return
