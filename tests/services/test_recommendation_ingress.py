from starlette.requests import Request

from src.app.services import recommendation_ingress as ingress


def _request() -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/api/v1/chat/query",
        "headers": [(b"x-api-key", b"test-key")],
        "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8080),
        "scheme": "http", "query_string": b"",
    })


def test_ingress_controls_and_quota_run_once_per_request_query(monkeypatch):
    calls = {"policy": 0, "rate": 0, "probe": 0, "quota": 0}
    monkeypatch.setattr(ingress, "enforce_model_theft_policy_gate", lambda **_kw: (
        calls.__setitem__("policy", calls["policy"] + 1) or True, "ok"))
    monkeypatch.setattr(ingress, "enforce_model_theft_rate_limit", lambda **_kw: (
        calls.__setitem__("rate", calls["rate"] + 1) or True, "ok"))
    monkeypatch.setattr(ingress, "detect_systematic_probing", lambda **_kw: (
        calls.__setitem__("probe", calls["probe"] + 1) or {"detected": False}))

    class Quota:
        def __init__(self, _redis):
            pass

        def check_and_consume(self, *_args, **_kwargs):
            calls["quota"] += 1
            return True, {}

    monkeypatch.setattr(ingress, "TenantQuotaGuard", Quota)
    request = _request()
    first = ingress.authorize_recommendation_ingress(
        request=request, redis=object(), query="gaming laptop", uid="u1", tenant_id="t1")
    second = ingress.authorize_recommendation_ingress(
        request=request, redis=object(), query="gaming laptop", uid="u1", tenant_id="t1")

    assert first == second
    assert calls == {"policy": 1, "rate": 1, "probe": 1, "quota": 1}


def test_ingress_reauthorizes_when_query_changes(monkeypatch):
    calls = {"quota": 0}
    monkeypatch.setattr(ingress, "enforce_model_theft_policy_gate", lambda **_kw: (True, "ok"))
    monkeypatch.setattr(ingress, "enforce_model_theft_rate_limit", lambda **_kw: (True, "ok"))
    monkeypatch.setattr(ingress, "detect_systematic_probing", lambda **_kw: {"detected": False})

    class Quota:
        def __init__(self, _redis):
            pass

        def check_and_consume(self, *_args, **_kwargs):
            calls["quota"] += 1
            return True, {}

    monkeypatch.setattr(ingress, "TenantQuotaGuard", Quota)
    request = _request()
    for query in ("laptop", "tablet"):
        ingress.authorize_recommendation_ingress(
            request=request, redis=object(), query=query, uid="u1", tenant_id="t1")

    assert calls["quota"] == 2
