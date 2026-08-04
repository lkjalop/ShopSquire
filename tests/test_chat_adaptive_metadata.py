from src.app.routers.chat import _include_adaptive_metadata


def test_disabled_adaptive_fields_are_absent_not_null():
    output = {"products": []}

    _include_adaptive_metadata(output, {
        "sales_response_nudge": None,
        "ranking_experiment": None,
        "storefront_emphasis": "disabled",
    })

    assert output == {"products": []}


def test_only_materialized_adaptive_fields_are_forwarded():
    output = {}
    experiment = {"experiment_id": "ranking-nudge", "variant": "treatment"}

    _include_adaptive_metadata(output, {"ranking_experiment": experiment})

    assert output == {"ranking_experiment": experiment}
