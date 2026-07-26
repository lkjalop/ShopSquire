from src.app.routers.recommend import router as legacy_router
from src.app.routers.recommendation_checkout import router as checkout_router
from src.app.routers.recommendation_feedback import router as feedback_router


def _paths(router) -> set[str]:
    return {route.path for route in router.routes}


def test_extracted_recommendation_endpoints_have_single_router_owner():
    legacy_paths = _paths(legacy_router)
    assert "/api/v1/recommend/checkout_upsell" not in legacy_paths
    assert "/api/v1/recommend/interaction" not in legacy_paths
    assert "/api/v1/recommend/feedback" not in legacy_paths

    assert "/api/v1/recommend/checkout_upsell" in _paths(checkout_router)
    assert {
        "/api/v1/recommend/interaction",
        "/api/v1/recommend/feedback",
    }.issubset(_paths(feedback_router))
