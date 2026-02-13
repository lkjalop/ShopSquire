"""create vectors table for pgvector

Revision ID: a9d8c7b6e5f4
Revises: f4a8c2d6e0b1
Create Date: 2026-02-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a9d8c7b6e5f4"
down_revision = "f4a8c2d6e0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    # Only create when it doesn't exist
    if not insp.has_table("vectors"):
        # Try Postgres + pgvector first
        try:
            dialect = getattr(getattr(bind, 'dialect', None), 'name', '') or ''
        except Exception:
            dialect = ''

        if "postgres" in dialect:
            # Detect whether pgvector is available before attempting DDL that would
            # abort the transaction if the type does not exist.
            has_pgvector = False
            try:
                # Prefer extension check; fall back to type existence.
                ext_row = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar()
                type_row = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector')")).scalar()
                has_pgvector = bool(ext_row) or bool(type_row)
            except Exception:
                has_pgvector = False

            if has_pgvector:
                # Safe path: create table using pgvector type
                op.execute("CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, embedding vector(1536), payload JSONB)")
                # best-effort ivfflat index (ignore errors if not supported)
                try:
                    op.execute("CREATE INDEX IF NOT EXISTS idx_vectors_embedding ON vectors USING ivfflat (embedding)")
                except Exception:
                    pass
            else:
                # Fallback: create table with TEXT embedding when pgvector is unavailable
                op.execute("CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, embedding TEXT, payload JSONB)")
        else:
            # SQLite / generic fallback
            try:
                op.create_table(
                    "vectors",
                    sa.Column("id", sa.Text(), primary_key=True),
                    sa.Column("embedding", sa.Text(), nullable=True),
                    sa.Column("payload", sa.Text(), nullable=True),
                )
            except Exception:
                pass


def downgrade() -> None:
    try:
        op.drop_table("vectors")
    except Exception:
        pass
