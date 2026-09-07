from src.app import config


def test_public_readiness_contract_allowlists_fields_not_secret_names(monkeypatch):
    monkeypatch.setattr(config, "canonical_runtime_contract", lambda: {
        "API_BASE_URL": "http://127.0.0.1:8080", "API_PORT": 8080,
        "FEATURE_FLAGS_PATH": "config/feature_flags.json",
        "DATABASE_URL": "postgresql://buyer:secret-db@db/internal",
        "REDIS_URL": "redis://:secret-redis@cache/0",
        "MERCHANT_API_KEY": "secret-merchant", "OWNER_API_KEY": "secret-owner",
        "DEVELOPER_API_KEY": "secret-developer", "GOOGLE_AI_API_KEY": "secret-model",
        "FUTURE_CREDENTIAL": "secret-future",
    })
    report = config.validate_runtime_contract()
    assert report["ok"] is True
    assert "secret-" not in str(report)
    assert not ({"DATABASE_URL", "REDIS_URL", "OWNER_API_KEY", "FUTURE_CREDENTIAL"}
                & report["contract"].keys())
    assert report["contract"]["API_PORT"] == 8080
