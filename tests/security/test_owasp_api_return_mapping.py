from src.app.security.owasp_map import TAXONOMY_EDITIONS, map_signals_to_owasp_api


def test_return_authorization_and_upstream_failures_map_to_versioned_api_controls():
    tags = map_signals_to_owasp_api({
        "foreign_order_reference": True,
        "unauthorized_return_transition": True,
        "untrusted_order_or_carrier_api": True,
    })
    assert tags == [
        "API10:2023 Unsafe Consumption of APIs",
        "API1:2023 Broken Object Level Authorization",
        "API5:2023 Broken Function Level Authorization",
    ]
    assert TAXONOMY_EDITIONS["owasp_api"] == "OWASP API Security Top 10 2023"
