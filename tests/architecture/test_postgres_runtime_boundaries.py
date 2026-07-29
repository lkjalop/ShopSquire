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


def test_supplier_catalog_runtime_ddl_is_sqlite_only() -> None:
    source = (
        ROOT / "src/app/services/supplier_catalog.py"
    ).read_text(encoding="utf-8")
    function = source.split(
        "def ensure_tables(db) -> None:", 1,
    )[1].split("\ndef _ensure_supplier_products_columns", 1)[0]
    assert 'if dialect != "sqlite":' in function
    assert "return" in function


def test_taxonomy_registry_runtime_ddl_is_sqlite_only() -> None:
    source = (
        ROOT / "src/app/services/taxonomy_registry.py"
    ).read_text(encoding="utf-8")
    function = source.split(
        "def ensure_tables(db) -> None:", 1,
    )[1].split("\ndef ", 1)[0]
    assert 'dialect != "sqlite"' in function
    assert "return" in function


def test_supplier_baseline_runtime_ddl_is_sqlite_only() -> None:
    source = (
        ROOT / "src/app/security/supplier_baseline.py"
    ).read_text(encoding="utf-8")
    function = source.split(
        "def _ensure_tables() -> None:", 1,
    )[1].split("\ndef ", 1)[0]
    assert 'dialect != "sqlite"' in function
    assert "return" in function


def test_fulfillment_repository_runtime_ddl_is_sqlite_only() -> None:
    source = (
        ROOT / "src/app/services/fulfillment/repository.py"
    ).read_text(encoding="utf-8")
    function = source.split(
        "def ensure_tables(db) -> None:", 1,
    )[1].split("\ndef ", 1)[0]
    assert 'dialect != "sqlite"' in function
    assert "return" in function
