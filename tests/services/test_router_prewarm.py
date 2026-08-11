from types import SimpleNamespace

from src.app import main


def test_demo_v2_does_not_warm_vlm_unless_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("SHOPSQUIRE_RUNTIME_PROFILE", "demo_v2")
    monkeypatch.delenv("VLM_WARMUP_ON_START", raising=False)
    assert main._vlm_warmup_enabled() is False

    monkeypatch.setenv("VLM_WARMUP_ON_START", "1")
    assert main._vlm_warmup_enabled() is True


def test_non_demo_profile_preserves_default_vlm_warmup(monkeypatch):
    monkeypatch.setenv("SHOPSQUIRE_RUNTIME_PROFILE", "production")
    monkeypatch.delenv("VLM_WARMUP_ON_START", raising=False)
    assert main._vlm_warmup_enabled() is True


def test_router_prewarm_records_success(monkeypatch):
    calls = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

    def _post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._router_http_post", _post,
    )
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

    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._router_http_post", _fail,
    )
    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._router_model",
        lambda: "router-model",
    )
    app = SimpleNamespace(state=SimpleNamespace())

    result = main._prewarm_router_models(app)

    assert result["ready"] is False
    assert result["error"] == "cold model timed out"
    assert app.state.router_prewarm == result
