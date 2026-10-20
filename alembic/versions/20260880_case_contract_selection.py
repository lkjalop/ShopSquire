"""Persist explicit, revision-bound buyer requirement contracts."""
from alembic import op
import sqlalchemy as sa

revision = "20260880_case_contract_selection"
down_revision = "20260879_refund_effect_permit"
branch_labels = None
depends_on = None
preserve_history_on_downgrade = True


def upgrade():
    op.create_table("shopping_case_contract_selections",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.Text(), nullable=False),
        sa.Column("contract_revision", sa.Text(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("selected_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(), nullable=True),
        sa.UniqueConstraint("tenant_id", "case_id", "case_revision", name="uq_case_contract_revision"))


def downgrade():
    raise RuntimeError("Contract selection history must be preserved; use an explicit data migration.")
