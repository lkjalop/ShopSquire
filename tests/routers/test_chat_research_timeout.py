from src.app.routers import chat


def test_automatic_research_timeout_covers_complete_pipeline(monkeypatch):
    monkeypatch.delenv("AUTOMATIC_RESEARCH_TIMEOUT_SEC", raising=False)
    assert chat._automatic_research_timeout_seconds() == 45.0


def test_automatic_research_timeout_is_bounded(monkeypatch):
    monkeypatch.setenv("AUTOMATIC_RESEARCH_TIMEOUT_SEC", "2")
    assert chat._automatic_research_timeout_seconds() == 10.0
    monkeypatch.setenv("AUTOMATIC_RESEARCH_TIMEOUT_SEC", "999")
    assert chat._automatic_research_timeout_seconds() == 120.0
    monkeypatch.setenv("AUTOMATIC_RESEARCH_TIMEOUT_SEC", "invalid")
    assert chat._automatic_research_timeout_seconds() == 45.0
