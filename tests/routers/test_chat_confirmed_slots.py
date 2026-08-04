from src.app.routers.chat import _extract_confirmed_slots


def test_core_brand_exclusion_wins_over_legacy_positive_mention():
    slots = _extract_confirmed_slots(
        query="a work laptop under $1900, not Apple",
        response={
            "constraints_used": {
                "brands": [],
                "brand_excludes": ["Apple"],
            }
        },
    )

    assert slots["budget_max"] == 1900
    assert slots["brand_excludes"] == ["Apple"]
    assert "brands" not in slots


def test_explicit_total_budget_is_preserved_for_followup_cart_turns():
    slots = _extract_confirmed_slots(
        query="Make that quantity 50 and set the total budget to AUD 110,000.",
        response={},
    )

    assert slots["budget_scope"] == "total"
    assert slots["total_budget_cents"] == 11_000_000
    assert slots["budget_max"] == 110_000
