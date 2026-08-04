"""Record authority and provenance for Party external identities.

Revision ID: 20260827_party_identity_authority
Revises: 20260826_communication_lifecycle
"""
from alembic import op
import sqlalchemy as sa


revision = "20260827_party_identity_authority"
down_revision = "20260826_communication_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "party_external_identity" not in inspector.get_table_names():
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("party_external_identity")
    }
    if "authority" not in columns:
        op.add_column(
            "party_external_identity",
            sa.Column("authority", sa.Text(), nullable=False, server_default="legacy_unverified"),
        )
    if "provenance_ref" not in columns:
        op.add_column(
            "party_external_identity",
            sa.Column("provenance_ref", sa.Text()),
        )
    if "verified_at" not in columns:
        op.add_column(
            "party_external_identity",
            sa.Column("verified_at", sa.DateTime(timezone=True)),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "party_external_identity" not in inspector.get_table_names():
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("party_external_identity")
    }
    for name in ("verified_at", "provenance_ref", "authority"):
        if name in columns:
            op.drop_column("party_external_identity", name)
