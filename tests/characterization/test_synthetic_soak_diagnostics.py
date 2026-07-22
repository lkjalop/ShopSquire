from tests.characterization.synthetic_conversation_soak import _routing_calibration_summary


def test_routing_calibration_uses_authored_class_not_query_reparse():
    rows = [
        {
            "query": "arbitrary wording",
            "lane": "SEARCH",
            "calibration_class": "brand_refinement",
            "errors": ["lane:SEARCH:expected:FILTER"],
        },
        {
            "query": "another arbitrary wording",
            "lane": "FILTER",
            "calibration_class": "sort_refinement",
            "errors": [],
        },
    ]

    result = _routing_calibration_summary(rows)

    assert result["misses"] == 1
    assert result["by_class"] == {"brand_refinement": 1}
    assert result["classes"][0]["expected"] == ["FILTER"]
