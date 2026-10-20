"""Record explicit, revision-bound buyer selection of reviewed supplier estimates."""
from alembic import op

revision = '20260892_buyer_supplier_selection'
down_revision = '20260891_governed_product_offers'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE buyer_supplier_quote_selection (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
        uid TEXT NOT NULL, case_revision INTEGER NOT NULL, quote_id TEXT NOT NULL,
        quote_digest TEXT NOT NULL, quote_json TEXT NOT NULL, accepted_at TEXT NOT NULL,
        UNIQUE(tenant_id,case_id,case_revision))''')


def downgrade():
    op.drop_table('buyer_supplier_quote_selection')
