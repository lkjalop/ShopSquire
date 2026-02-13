"""Initial empty migration scaffold.

Revision ID: 0001_init_empty
Revises: 
Create Date: 2026-01-27 00:00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_init_empty'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # This is an empty initial migration. Future autogenerates will populate.
    pass


def downgrade():
    pass
