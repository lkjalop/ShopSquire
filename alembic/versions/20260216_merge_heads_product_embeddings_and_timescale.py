"""merge heads: product_embeddings + timescale security cagg

Revision ID: 20260216_merge_heads
Revises: 20260210_product_embeddings, a9b7c5d3e1f0
Create Date: 2026-02-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op  # noqa: F401

# This merge revision resolves multiple Alembic heads so Docker startup
# migrations (alembic upgrade head) can run deterministically.
revision = "20260216_merge_heads"
down_revision = ("20260210_product_embeddings", "a9b7c5d3e1f0")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Merge only; no schema changes.
    pass


def downgrade() -> None:
    # Merge only; no schema changes.
    pass

