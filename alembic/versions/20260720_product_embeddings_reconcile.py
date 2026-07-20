"""reconcile product embeddings into the canonical pgvector table

Revision ID: 20260720_product_embeddings_reconcile
Revises: 20260718_fulfillment_draft_retry
Create Date: 2026-07-20

The historical migrations could create either ``oltp.product_embeddings`` with
a text column or ``public.product_embeddings`` with a vector column. Runtime
connections search ``oltp`` first, so one installation could silently read a
different table from the one populated by another installation.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op


revision = "20260720_product_embeddings_reconcile"
down_revision = "20260718_fulfillment_draft_retry"
branch_labels = None
depends_on = None


def _table_exists(bind, qualified_name: str) -> bool:
    return bool(bind.execute(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": qualified_name}).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(getattr(bind.dialect, "name", "")).lower()
    if "sqlite" in dialect:
        # Local/demo databases use text-serialized vectors. This keeps the health and
        # repository contracts available without pretending SQLite provides pgvector.
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS product_embeddings (
                product_id TEXT PRIMARY KEY,
                embedding TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return
    if "postgres" not in dialect:
        return

    available = bool(bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='vector')"
    )).scalar())
    if not available:
        logging.getLogger("alembic.pgvector").warning(
            "pgvector is unavailable; product embedding reconciliation was skipped"
        )
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS oltp")

    if not _table_exists(bind, "oltp.product_embeddings"):
        op.execute(
            """
            CREATE TABLE oltp.product_embeddings (
                product_id TEXT PRIMARY KEY,
                embedding vector(1536),
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    else:
        column_type = bind.execute(sa.text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema='oltp' AND table_name='product_embeddings'
              AND column_name='embedding'
            """
        )).scalar()
        if str(column_type or "").lower() != "vector":
            op.execute(
                """
                ALTER TABLE oltp.product_embeddings
                ALTER COLUMN embedding TYPE vector(1536)
                USING CASE
                    WHEN embedding IS NULL OR btrim(embedding::text) = '' THEN NULL
                    ELSE embedding::text::vector(1536)
                END
                """
            )

    if _table_exists(bind, "public.product_embeddings"):
        public_type = bind.execute(sa.text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='product_embeddings'
              AND column_name='embedding'
            """
        )).scalar()
        cast_expr = "embedding" if str(public_type or "").lower() == "vector" else "embedding::text::vector(1536)"
        op.execute(
            f"""
            INSERT INTO oltp.product_embeddings (product_id, embedding, updated_at)
            SELECT product_id, {cast_expr}, NULLIF(updated_at::text, '')::timestamptz
            FROM public.product_embeddings
            ON CONFLICT (product_id) DO UPDATE
            SET embedding = EXCLUDED.embedding, updated_at = EXCLUDED.updated_at
            """
        )
        op.execute("DROP TABLE public.product_embeddings")

    op.execute("DROP INDEX IF EXISTS oltp.idx_product_embeddings")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_product_embeddings_hnsw
        ON oltp.product_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "postgres" not in str(getattr(bind.dialect, "name", "")).lower():
        return
    op.execute("DROP INDEX IF EXISTS oltp.idx_product_embeddings_hnsw")
