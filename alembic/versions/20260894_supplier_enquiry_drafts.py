"""Persist reviewed versions without altering legacy messages or approvals."""

from alembic import op
import sqlalchemy as sa

revision = "20260894_supplier_enquiry_drafts"
down_revision = "20260893_security_tenant_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE supplier_enquiry_draft (
 tenant_id TEXT NOT NULL,enquiry_id TEXT NOT NULL,version INTEGER NOT NULL,
 content_hash TEXT NOT NULL,draft_json TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,enquiry_id,version))""")


def downgrade():
    # Empty fixture tails are reversible; reviewed history must survive.
    if op.get_bind().execute(sa.text("SELECT 1 FROM supplier_enquiry_draft LIMIT 1")).first():
        raise RuntimeError("supplier_draft_history_requires_restore_from_backup")
    op.drop_table("supplier_enquiry_draft")
