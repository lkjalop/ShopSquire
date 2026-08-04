from src.app.routers import recommend_compat, recommendation_feedback


def _paths(router):
    return {route.path for route in router.routes}


def test_feedback_routes_have_independent_owner():
    owned = _paths(recommendation_feedback.router)

    assert "/api/v1/recommend/interaction" in owned
    assert "/api/v1/recommend/feedback" in owned
    assert "/api/v1/recommend/interaction" not in _paths(recommend_compat.router)
    assert "/api/v1/recommend/feedback" not in _paths(recommend_compat.router)
