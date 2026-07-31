from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_general_ci_has_hard_job_and_test_deadlines() -> None:
    workflow = (ROOT / ".github/workflows/ci-tests.yml").read_text(encoding="utf-8")

    assert "timeout-minutes:" in workflow
    assert "timeout --signal=TERM --kill-after=30s" in workflow
    assert "--timeout=120 --timeout-method=thread" in workflow


def test_general_ci_does_not_duplicate_specialist_suites() -> None:
    workflow = (ROOT / ".github/workflows/ci-tests.yml").read_text(encoding="utf-8")

    for specialist in (
        "tests/services",
        "tests/e2e",
        "tests/pw",
        "tests/playwright",
        "tests/browser",
        "tests/load",
    ):
        assert f"! -path '{specialist}/*'" in workflow


def test_general_ci_template_is_migration_first_and_copy_safe() -> None:
    workflow = (ROOT / ".github/workflows/ci-tests.yml").read_text(encoding="utf-8")
    test_harness = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")

    assert "python -m alembic upgrade head" in workflow
    assert '[sys.executable, "-m", "alembic", "heads"]' in workflow
    assert "revisions != heads" in workflow
    assert "scripts/seed_products.py" in workflow
    assert 'TEST_USE_PROVIDED_DATABASE: "1"' in workflow
    assert "ensure_metadata" not in workflow
    assert 'PRAGMA wal_checkpoint(TRUNCATE)' in workflow
    assert 'PRAGMA integrity_check' in workflow
    assert "SELECT version_num FROM alembic_version" in workflow
    assert 'cp --reflink=auto "$template_db" "$db_path"' in workflow
    assert 'rm -f "$template_db" "$template_db-shm" "$template_db-wal"' in workflow
    assert 'os.getenv("TEST_USE_PROVIDED_DATABASE"' in test_harness
    assert "session_db_url = os.environ.get(\"DATABASE_URL\"" in test_harness


def test_postgres_matrix_runs_owned_contracts_with_a_deadline() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert workflow.count("timeout-minutes:") >= 2
    assert "timeout --signal=TERM --kill-after=30s" in workflow
    assert "tests/chaos/test_money_concurrency_postgres.py" in workflow
    assert "tests/architecture/test_postgres_security_boundaries.py" in workflow
    assert "--cov-fail-under" not in workflow
