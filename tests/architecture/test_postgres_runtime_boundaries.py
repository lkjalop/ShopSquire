from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_testing_environment_retains_localhost_browser_cors() -> None:
    source = (ROOT / "src/app/main.py").read_text(encoding="utf-8")
    assert '"test", "testing"' in source


def test_escalation_runtime_ddl_is_sqlite_only() -> None:
    source = (
        ROOT / "src/app/routers/escalation_room.py"
    ).read_text(encoding="utf-8")
    function = source.split(
        "def _ensure_incident_runtime_tables() -> None:", 1,
    )[1].split("\ndef _allow_public_escalation", 1)[0]
    assert 'if eng.dialect.name != "sqlite":' in function
    assert "return" in function
