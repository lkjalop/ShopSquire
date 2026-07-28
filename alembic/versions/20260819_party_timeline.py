"""Add governed Party identity proposal attribution.

Revision ID: 20260819_party_timeline
Revises: 20260818_public_market_fetch
"""

from alembic import op
import sqlalchemy as sa


revision = "20260819_party_timeline"
down_revision = "20260818_public_market_fetch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "identity_resolution_decision" not in set(inspector.get_table_names()):
        return
    columns = {
        str(column["name"])
        for column in inspector.get_columns("identity_resolution_decision")
    }
    if "proposed_by" not in columns:
        op.add_column(
            "identity_resolution_decision",
            sa.Column("proposed_by", sa.Text()),
        )
    if "resolution_note" not in columns:
        op.add_column(
            "identity_resolution_decision",
            sa.Column("resolution_note", sa.Text()),
        )
    # The original foundation temporarily stored the proposer in resolved_by. Preserve that
    # attribution while restoring the semantic invariant that unresolved rows have no resolver.
    op.execute(
        sa.text(
            """
            UPDATE identity_resolution_decision
            SET proposed_by=COALESCE(proposed_by, resolved_by),
                resolved_by=CASE WHEN status='proposed' THEN NULL ELSE resolved_by END
            """
        )
    )


def downgrade() -> None:
    # Human identity-review attribution is audit evidence and remains retained.
    return
