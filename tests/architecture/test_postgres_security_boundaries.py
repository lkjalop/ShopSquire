from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_admin_security_paths_do_not_mutate_schema_at_runtime():
    source = (ROOT / "src/app/routers/admin.py").read_text(encoding="utf-8")

    assert "def _ensure_security_event_correction_columns" not in source
    security_events_start = source.index("def get_security_events(")
    security_events_end = source.index("\ndef security_metrics(", security_events_start)
    assert "CREATE TABLE" not in source[security_events_start:security_events_end]


def test_postgres_boolean_security_queries_are_not_integer_comparisons():
    admin = (ROOT / "src/app/routers/admin.py").read_text(encoding="utf-8")
    escalation = (ROOT / "src/app/security/escalation.py").read_text(encoding="utf-8")
    main = (ROOT / "src/app/main.py").read_text(encoding="utf-8")

    assert "escalated = 1" not in admin
    assert "blocked = 1" not in admin
    assert "SET escalated = 1" not in escalation
    assert "COALESCE(active, 1) = 1" not in main
