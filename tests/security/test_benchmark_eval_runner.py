from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_RUNNER_PATH = Path(__file__).resolve().parent / "benchmarks" / "eval_runner.py"
_SPEC = spec_from_file_location("benchmark_eval_runner", _RUNNER_PATH)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
run_benchmark = _MODULE.run_benchmark


def test_benchmark_runner_emits_metrics_and_results() -> None:
    out = run_benchmark()
    assert out["case_count"] >= 3
    assert "precision_proxy" in out
    assert "false_positive_leak_rate" in out
    assert isinstance(out["results"], list) and out["results"]
    by_id = {row["id"]: row for row in out["results"]}
    assert "payment_fraud_attachment_triplet" in by_id
    assert "benign_comment_only_vba_source" in by_id
    assert by_id["payment_fraud_attachment_triplet"]["mitre_atlas"] == []
    assert by_id["benign_comment_only_vba_source"]["mitre_attack"] == []
