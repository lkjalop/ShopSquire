from fastapi import FastAPI

from src.app.bootstrap.recommendation_router_group import register_recommendation_router_group


def test_recommendation_group_retains_compatibility_and_companion_surfaces():
    app = FastAPI()
    registered = register_recommendation_router_group(app)
    paths = {route.path for route in app.routes}
    assert registered[0] == "recommend_v2_compatibility"
    assert app.state.recommend_v2_compatibility_retained is True
    assert "/api/v1/recommend/suggest" in paths
    assert "recommendation_explain" in registered
    assert "recommendation_checkout" in registered
