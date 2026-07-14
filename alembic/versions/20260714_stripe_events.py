"""Money-P0 M4: stripe_events dedup table (process each webhook once)."""
from alembic import op
import sqlalchemy as sa

revision = "20260714_stripe_events"
down_revision = "20260714_refund_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "stripe_events" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "stripe_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "stripe_events" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("stripe_events")
