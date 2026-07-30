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
        assert f"--ignore={specialist}" in workflow


def test_postgres_matrix_runs_owned_contracts_with_a_deadline() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert workflow.count("timeout-minutes:") >= 2
    assert "timeout --signal=TERM --kill-after=30s" in workflow
    assert "tests/chaos/test_money_concurrency_postgres.py" in workflow
    assert "tests/architecture/test_postgres_security_boundaries.py" in workflow
    assert "--cov-fail-under" not in workflow
