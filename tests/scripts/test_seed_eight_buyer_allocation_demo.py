from __future__ import annotations

from contextlib import AbstractContextManager

from scripts.seed_eight_buyer_allocation_demo import _run_optional_enrichment


class _NestedTransaction(AbstractContextManager):
    def __exit__(self, exc_type, exc, traceback):
        return False


class _Database:
    def __init__(self, *, fail_health_probe: bool = False) -> None:
        self.fail_health_probe = fail_health_probe

    def begin_nested(self):
        return _NestedTransaction()

    def execute(self, _statement):
        if self.fail_health_probe:
            raise RuntimeError("postgres transaction aborted by swallowed query error")
        return None


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
        _Database(fail_health_probe=True),
        label="qualified_substitute",
        operation=lambda: [],
    )

    assert result["status"] == "degraded"
    assert "transaction aborted" in result["reason"]
