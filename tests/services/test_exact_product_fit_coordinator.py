from types import SimpleNamespace

from src.app.services.recommendation_core.exact_product_fit_coordinator import (
    coordinate_exact_product_fit,
)


def test_selected_product_outside_authorized_slate_is_not_substituted():
    envelope = SimpleNamespace(
        session={}, external_research_consent=False, tenant_id="tenant-a",
    )
    decision = SimpleNamespace(
        secondary_lanes=("EXPLAIN",), exact_product_sku="SKU-MISSING",
        requirements={},
    )
    response = SimpleNamespace(
        products=[SimpleNamespace(sku="SKU-RETURNED")], extras={}, message="Found one.",
    )

    coordinate_exact_product_fit(object(), envelope, decision, response)

    assert response.extras["explanation"]["status"] == (
        "selected_product_not_in_authorized_slate"
    )
    assert response.extras["explanation"]["sku"] == "SKU-MISSING"
    assert "will not substitute" in response.message


def test_fit_coordinator_is_inert_without_explanation_obligation():
    response = SimpleNamespace(products=[SimpleNamespace(sku="SKU-1")], extras={}, message="x")
    coordinate_exact_product_fit(
        object(), SimpleNamespace(),
        SimpleNamespace(secondary_lanes=(), exact_product_sku=None), response,
    )
    assert response.extras == {}
    assert response.message == "x"
