"""Explicit buyer acceptance of evidence-bound product offers."""
from alembic import op
revision='20260891_governed_product_offers'
down_revision='20260890_supplier_enquiry_journey'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('''CREATE TABLE governed_product_offer (
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,case_id TEXT NOT NULL,uid TEXT NOT NULL,
 case_revision INTEGER NOT NULL,cart_id TEXT NOT NULL,cart_version INTEGER NOT NULL,
 input_json TEXT NOT NULL,projection_json TEXT NOT NULL,projection_digest TEXT NOT NULL,
 expires_at TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT)''')

def downgrade():op.drop_table('governed_product_offer')
