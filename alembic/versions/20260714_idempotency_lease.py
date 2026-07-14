"""Money-P0 M2: idempotency lease/owner columns for reservation reclaim."""
from alembic import op
import sqlalchemy as sa

revision = "20260714_idempotency_lease"
down_revision = "20260714_payment_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("idempotency_keys")}
    additions = {
        "owner_token": sa.Column("owner_token", sa.Text(), nullable=True),
        "lease_expires_at": sa.Column("lease_expires_at", sa.Float(), nullable=True),
        "updated_at": sa.Column("updated_at", sa.Text(), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("idempotency_keys", column)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("idempotency_keys")}
    for name in ("updated_at", "lease_expires_at", "owner_token"):
        if name in columns:
            op.drop_column("idempotency_keys", name)
