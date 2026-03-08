import os


def test_p0_eval_harness_metrics_shape():
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_p0_eval.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_p0_eval.db")
    os.environ.setdefault("SEMANTIC_BEC_ENABLED", "1")
    os.environ.setdefault("SEMANTIC_BEC_REVIEW_THRESHOLD", "0.2")
    os.environ.setdefault("SEMANTIC_BEC_SECURITY_THRESHOLD", "0.35")

    from src.app.security.email_security_eval_harness import run_p0_eval

    out = run_p0_eval()
    summary = out.get("summary") or {}
    assert summary.get("total", 0) >= 6
    for key in ("precision", "recall", "fpr"):
        v = float(summary.get(key, 0.0))
        assert 0.0 <= v <= 1.0

    cases = out.get("cases") or []
    assert isinstance(cases, list) and cases
    one = cases[0]
    assert "semantic_bec_score" in one
    assert "yara_match_count" in one
