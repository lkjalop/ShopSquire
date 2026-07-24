from src.app.main import app


def _owners(path: str, method: str) -> list[str]:
    return [
        route.endpoint.__module__
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
    ]


def test_narration_and_cf_routes_have_one_nonlegacy_owner():
    assert _owners("/api/v1/recommend/narration/{job_id}", "GET") == [
        "src.app.routers.recommend_aux"
    ]
    assert _owners("/api/v1/recommend/cf/train", "POST") == [
        "src.app.routers.recommend_aux"
    ]
