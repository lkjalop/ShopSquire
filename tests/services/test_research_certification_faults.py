from src.app.services.research_certification_faults import active_research_fault


def test_fault_profile_requires_explicit_non_production_certification(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_CERTIFICATION_FAULT_PROFILE", "publisher_timeout")
    monkeypatch.delenv("RESEARCH_CERTIFICATION_MODE", raising=False)
    assert active_research_fault() is None

    monkeypatch.setenv("RESEARCH_CERTIFICATION_MODE", "1")
    monkeypatch.setenv("APP_ENV", "production")
    assert active_research_fault() is None

    monkeypatch.setenv("APP_ENV", "development")
    assert active_research_fault() == "publisher_timeout"


def test_unknown_fault_profile_is_inert(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_CERTIFICATION_MODE", "1")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("RESEARCH_CERTIFICATION_FAULT_PROFILE", "invent_authority")
    assert active_research_fault() is None
