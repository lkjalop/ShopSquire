from src.app.services.schema_policy import runtime_ddl_allowed


def test_runtime_ddl_is_local_only_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_RUNTIME_DDL", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert runtime_ddl_allowed() is False
    monkeypatch.setenv("APP_ENV", "test")
    assert runtime_ddl_allowed() is True


def test_runtime_ddl_override_is_explicit(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_RUNTIME_DDL", "1")
    assert runtime_ddl_allowed() is True
    monkeypatch.setenv("ALLOW_RUNTIME_DDL", "0")
    assert runtime_ddl_allowed() is False
