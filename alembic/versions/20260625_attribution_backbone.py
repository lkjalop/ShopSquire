"""Attribution backbone schema + alembic head merge.

Adds the attribution capture tables (recommendation_decision, conversion_event) and the
orders.trace_id / orders.decision_id columns. Also MERGES the three pre-existing alembic
heads into one (3 -> 1) so `alembic upgrade head` is unambiguous again.

Dev/test create these via ORM ensure_metadata + services.attribution.ensure_tables(); this
migration is the prod-parity path. Fully idempotent (IF NOT EXISTS / add-column-if-missing),
so re-running or a partially-migrated DB is safe.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "20260625_attribution"
# Merge the three detected heads (see docs/SHOPSQUIRE_ATTRIBUTION_BACKBONE_ARCHITECTURE).
down_revision = ("20260210_product_embeddings", "a9b7c5d3e1f0", "20260614_authz_cp")
branch_labels = None
depends_on = None


def _ensure_col(table: str, col: str, coltype: sa.types.TypeEngine) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return
    cols = {c.get("name") for c in insp.get_columns(table)}
    if col not in cols:
        op.add_column(table, sa.Column(col, coltype, nullable=True))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("recommendation_decision"):
        op.create_table(
            "recommendation_decision",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("trace_id", sa.Text(), nullable=True),
            sa.Column("decision_id", sa.Text(), nullable=True),
            sa.Column("uid_hash", sa.Text(), nullable=True),
            sa.Column("surface", sa.Text(), nullable=True),
            sa.Column("arm", sa.Text(), nullable=True),
            sa.Column("variant", sa.Text(), nullable=True),
            sa.Column("skus_json", sa.Text(), nullable=True),
            sa.Column("context_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_recdecision_trace", "recommendation_decision", ["trace_id"])
        op.create_index("ix_recdecision_uid", "recommendation_decision", ["uid_hash"])

    if not insp.has_table("conversion_event"):
        op.create_table(
            "conversion_event",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("decision_id", sa.Text(), nullable=True),
            sa.Column("order_id", sa.Text(), nullable=True),
            sa.Column("uid_hash", sa.Text(), nullable=True),
            sa.Column("attributed_skus_json", sa.Text(), nullable=True),
            sa.Column("value_cents", sa.Integer(), nullable=True),
            sa.Column("window_s", sa.Integer(), nullable=True),
            sa.Column("attribution_model", sa.Text(), nullable=True),
            sa.Column("converted_at", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_convevent_order", "conversion_event", ["order_id"])
        op.create_index("ix_convevent_decision", "conversion_event", ["decision_id"])

    # Order attribution columns (E1 populates trace_id at order creation).
    _ensure_col("orders", "trace_id", sa.Text())
    _ensure_col("orders", "decision_id", sa.Text())


def downgrade() -> None:
    for idx, tbl in (
        ("ix_convevent_order", "conversion_event"),
        ("ix_convevent_decision", "conversion_event"),
        ("ix_recdecision_trace", "recommendation_decision"),
        ("ix_recdecision_uid", "recommendation_decision"),
    ):
        try:
            op.drop_index(idx, table_name=tbl)
        except Exception:
            pass
    for tbl in ("conversion_event", "recommendation_decision"):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
