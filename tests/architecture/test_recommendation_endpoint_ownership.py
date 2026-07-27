from src.app.routers.recommend_compat import router as compatibility_router
from src.app.routers.recommendation_checkout import router as checkout_router
from src.app.routers.recommendation_feedback import router as feedback_router
from src.app.routers.recommendation_explain import router as explain_router
from src.app.routers.recommendation_nqe import router as nqe_router


def _paths(router) -> set[str]:
    return {route.path for route in router.routes}


def test_extracted_recommendation_endpoints_have_single_router_owner():
    assert _paths(compatibility_router) == {"/api/v1/recommend/suggest"}

    assert "/api/v1/recommend/checkout_upsell" in _paths(checkout_router)
    assert {
        "/api/v1/recommend/interaction",
        "/api/v1/recommend/feedback",
    }.issubset(_paths(feedback_router))
    assert "/api/v1/recommend/why_product" in _paths(explain_router)
    assert {
        "/api/v1/recommend/nqe_slots",
        "/api/v1/recommend/nqe_feedback",
        "/api/v1/recommend/admin/nqe_feedback_summary",
    }.issubset(_paths(nqe_router))
