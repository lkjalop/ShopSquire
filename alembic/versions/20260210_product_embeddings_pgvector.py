"""add product_embeddings table with pgvector

Revision ID: 20260210_product_embeddings
Revises: a9d8c7b6e5f4
Create Date: 2026-02-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260210_product_embeddings"
down_revision = "a9d8c7b6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    # Ensure schema exists on Postgres
    if "postgres" in dialect:
        try:
            op.execute("CREATE SCHEMA IF NOT EXISTS oltp")
        except Exception:
            pass
        # Ensure pgvector extension/type is available
        has_pgvector = False
        try:
            ext_row = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar()
            type_row = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector')")).scalar()
            has_pgvector = bool(ext_row) or bool(type_row)
        except Exception:
            has_pgvector = False
        if has_pgvector:
            op.execute(
                "CREATE TABLE IF NOT EXISTS oltp.product_embeddings ("
                "  product_id TEXT PRIMARY KEY REFERENCES oltp.products(id) ON DELETE CASCADE,"
                "  embedding vector(1536),"
                "  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            # Best-effort ivfflat index for vector column
            try:
                op.execute("CREATE INDEX IF NOT EXISTS idx_product_embeddings ON oltp.product_embeddings USING ivfflat (embedding)")
            except Exception:
                pass
        else:
            # Fallback without pgvector
            try:
                op.execute(
                    "CREATE TABLE IF NOT EXISTS oltp.product_embeddings ("
                    "  product_id TEXT PRIMARY KEY,"
                    "  embedding TEXT,"
                    "  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            except Exception:
                pass
    else:
        # SQLite / generic fallback
        try:
            op.create_table(
                "product_embeddings",
                sa.Column("product_id", sa.Text(), primary_key=True),
                sa.Column("embedding", sa.Text(), nullable=True),
                sa.Column("updated_at", sa.Text(), nullable=True),
            )
        except Exception:
            pass


def downgrade() -> None:
    try:
        op.drop_table("product_embeddings")
    except Exception:
        pass
    # Postgres schema table drop (best-effort)
    try:
        op.execute("DROP TABLE IF EXISTS oltp.product_embeddings")
    except Exception:
        pass