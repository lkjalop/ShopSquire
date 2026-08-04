from src.app.services.recommend_nqe_stage import (
    resolve_nqe_product_category as _resolve_nqe_product_category,
)


def test_explicit_product_noun_wins_over_ambiguous_entity_alias():
    category = _resolve_nqe_product_category(
        query="20 laptops for a Unity lab, no Apple",
        constraints={},
        identity_constraints={},
        identity_result={},
    )

    assert category == "laptop"
