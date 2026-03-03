import uuid

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.checkout_upsell import ensure_recommend_interactions_table
from src.app.services.recommendation_als import train_recommend_als, ensure_recommend_cf_tables


def test_train_recommend_als_writes_scores():
    with db_session() as db:
        ensure_recommend_interactions_table(db)
        ensure_recommend_cf_tables(db)
        events = [
            ("u1", "SKU-A", "click"),
            ("u1", "SKU-A", "add_to_cart"),
            ("u1", "SKU-B", "click"),
            ("u2", "SKU-A", "click"),
            ("u2", "SKU-C", "add_to_cart"),
            ("u3", "SKU-B", "click"),
            ("u3", "SKU-C", "click"),
        ]
        for uid, sku, action in events:
            db.execute(
                text(
                    """
                    INSERT INTO recommend_interactions (id, uid_hash, sku, action, surface, trace_id, context_json)
                    VALUES (:id, :uid_hash, :sku, :action, 'test', '', '{}')
                    """
                ),
                {"id": str(uuid.uuid4()), "uid_hash": uid, "sku": sku, "action": action},
            )
        db.commit()
    out = train_recommend_als(lookback_days=180, topk_per_user=10, factors=6, iters=3)
    assert out.get("status") in {"ok", "no_data"}
    if out.get("status") == "ok":
        assert int(out.get("scores") or 0) > 0
