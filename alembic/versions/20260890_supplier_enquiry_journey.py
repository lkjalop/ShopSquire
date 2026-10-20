"""Case-bound enquiries, reviewed replies and revision-bound person permits."""
from alembic import op

revision='20260890_supplier_enquiry_journey'
down_revision='20260889_operator_inventory_requests'
branch_labels=None
depends_on=None


def upgrade():
    # DDL is frozen here so future service changes cannot alter migration history.
    op.execute('''CREATE TABLE supplier_enquiry_request (
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,case_id TEXT NOT NULL,case_revision INTEGER NOT NULL,
 requester_principal TEXT NOT NULL,supplier_ref TEXT NOT NULL,recipient TEXT NOT NULL,
 source_reference TEXT NOT NULL,sku TEXT NOT NULL,requested_quantity INTEGER NOT NULL,
 shortfall INTEGER NOT NULL,value_cents INTEGER NOT NULL,currency TEXT NOT NULL,
 status TEXT NOT NULL,approval_id TEXT,created_at TEXT NOT NULL,
 UNIQUE(tenant_id,source_reference))''')
    op.execute('''CREATE TABLE supplier_enquiry_reply (
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,enquiry_id TEXT NOT NULL,message_id TEXT NOT NULL,
 sender_ref TEXT NOT NULL,terms_json TEXT NOT NULL,payload_digest TEXT NOT NULL,
 status TEXT NOT NULL,reason TEXT NOT NULL,reviewer_principal TEXT,received_at TEXT NOT NULL,
 UNIQUE(tenant_id,message_id))''')
    op.execute('''CREATE TABLE person_effect_case_binding (
 tenant_id TEXT NOT NULL,approval_id TEXT NOT NULL,case_id TEXT NOT NULL,case_revision INTEGER NOT NULL,
 PRIMARY KEY(tenant_id,approval_id))''')


def downgrade():
    op.drop_table('person_effect_case_binding')
    op.drop_table('supplier_enquiry_reply')
    op.drop_table('supplier_enquiry_request')
