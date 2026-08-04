from __future__ import annotations

from contextlib import AbstractContextManager

from scripts.seed_eight_buyer_allocation_demo import _run_optional_enrichment


class _NestedTransaction(AbstractContextManager):
    def __init__(self, *, fail_on_exit: bool = False) -> None:
        self.fail_on_exit = fail_on_exit

    def __exit__(self, exc_type, exc, traceback):
        if self.fail_on_exit and exc_type is None:
            raise RuntimeError("postgres transaction aborted by swallowed query error")
        return False


class _Database:
    def __init__(self, *, fail_on_exit: bool = False) -> None:
        self.fail_on_exit = fail_on_exit

    def begin_nested(self):
        return _NestedTransaction(fail_on_exit=self.fail_on_exit)


def test_optional_enrichment_reports_success() -> None:
    result = _run_optional_enrichment(
        _Database(), label="qualified_substitute", operation=lambda: {"registered": True}
    )

    assert result == {
        "label": "qualified_substitute",
        "status": "applied",
        "value": {"registered": True},
    }


def test_optional_enrichment_contains_explicit_query_failure() -> None:
    def fail() -> None:
        raise ValueError("incompatible schema")

    result = _run_optional_enrichment(
        _Database(), label="approved_alternative_supplier", operation=fail
    )

    assert result["status"] == "degraded"
    assert result["reason"] == "ValueError: incompatible schema"


def test_optional_enrichment_detects_swallowed_postgres_abort() -> None:
    result = _run_optional_enrichment(
        _Database(fail_on_exit=True),
        label="qualified_substitute",
        operation=lambda: [],
    )

    assert result["status"] == "degraded"
    assert "transaction aborted" in result["reason"]
