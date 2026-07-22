from types import SimpleNamespace

from src.app import main


def test_router_prewarm_records_success(monkeypatch):
    calls = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

    def _post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr("httpx.post", _post)
    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._router_model",
        lambda: "router-model",
    )
    monkeypatch.setattr(
        "src.app.services.taxonomy_embedding_index.EMBED_MODEL",
        "embed-model",
    )
    app = SimpleNamespace(state=SimpleNamespace())

    result = main._prewarm_router_models(app)

    assert result["ready"] is True
    assert result["router_model"] == "router-model"
    assert result["embedding_model"] == "embed-model"
    assert app.state.router_prewarm == result
    assert [call[0].rsplit("/", 1)[-1] for call in calls] == ["embed", "generate"]


def test_router_prewarm_records_failure(monkeypatch):
    def _fail(*args, **kwargs):
        raise TimeoutError("cold model timed out")

    monkeypatch.setattr("httpx.post", _fail)
    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._router_model",
        lambda: "router-model",
    )
    app = SimpleNamespace(state=SimpleNamespace())

    result = main._prewarm_router_models(app)

    assert result["ready"] is False
    assert result["error"] == "cold model timed out"
    assert app.state.router_prewarm == result
