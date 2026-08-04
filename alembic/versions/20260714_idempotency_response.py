"""Upgrade legacy idempotency rows to fingerprinted durable-response storage."""
from alembic import op
import sqlalchemy as sa

revision = "20260714_idempotency_response"
down_revision = "20260714_draft_orders_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("idempotency_keys")}
    additions = {
        "fingerprint": sa.Column(
            "fingerprint", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
        "response_status": sa.Column("response_status", sa.Integer(), nullable=True),
        "response_body": sa.Column("response_body", sa.Text(), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("idempotency_keys", column)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("idempotency_keys")}
    for name in ("response_body", "response_status", "fingerprint"):
        if name in columns:
            op.drop_column("idempotency_keys", name)
