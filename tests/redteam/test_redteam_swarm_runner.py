from scripts.redteam_swarm_runner import run


def test_redteam_swarm_runner_outputs_categories(tmp_path):
    out_file = tmp_path / "redteam_report.json"
    report = run(out_path=str(out_file))
    assert isinstance(report, dict)
    assert "email" in report and "c2" in report
    assert isinstance(report["email"], list) and report["email"]
    assert isinstance(report["c2"], list) and report["c2"]
    assert out_file.exists() and out_file.stat().st_size > 0
