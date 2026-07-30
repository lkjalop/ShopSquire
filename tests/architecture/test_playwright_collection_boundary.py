from pathlib import Path


def test_disabled_playwright_conftest_does_not_abort_repository_collection():
    source = Path("tests/pw/conftest.py").read_text(encoding="utf-8")

    assert "def pytest_collection_modifyitems" in source
    prelude = source.split("# Ensure Playwright can spawn subprocesses", 1)[0]
    assert "\n    pytest.skip(" not in prelude
