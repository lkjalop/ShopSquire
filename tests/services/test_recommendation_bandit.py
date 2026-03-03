from src.app.models.db import db_session
from src.app.services.recommendation_bandit import (
    choose_recommendation_arm,
    ensure_recommend_bandit_tables,
    record_bandit_reward,
)


def test_bandit_choose_and_update():
    with db_session() as db:
        ensure_recommend_bandit_tables(db)
        chosen = choose_recommendation_arm(
            db,
            {"budget_tight": 1.0, "is_repeat_user": 1.0, "query_specificity": 0.8, "inventory_pressure": 0.2},
        )
        assert chosen.get("arm") in {"balanced", "explore_novelty", "price_value", "personalized_heavy"}
        record_bandit_reward(
            db,
            uid_hash="u-h1",
            sku="SKU-1",
            arm=str(chosen.get("arm")),
            reward=1.0,
            context={"budget_tight": 1.0, "is_repeat_user": 1.0, "query_specificity": 0.8, "inventory_pressure": 0.2},
        )
        chosen2 = choose_recommendation_arm(
            db,
            {"budget_tight": 1.0, "is_repeat_user": 1.0, "query_specificity": 0.8, "inventory_pressure": 0.2},
        )
    assert chosen2.get("arm") in {"balanced", "explore_novelty", "price_value", "personalized_heavy"}
