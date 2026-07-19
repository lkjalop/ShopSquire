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
