from __future__ import annotations

from src.app.security.redteam.suite import run_suite, REDTEAM_CASES


def test_redteam_suite_flags_high_risk():
    results = run_suite(REDTEAM_CASES)
    assert results
    for res in results:
        assert res["severity"] in ("warn", "high", "critical")
        assert isinstance(res.get("owasp_llm"), list)
