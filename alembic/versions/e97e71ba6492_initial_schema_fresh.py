"""
Generic Alembic revision script.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e97e71ba6492'
down_revision = 'b17cef4ec4bc'
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass