import json

from scripts import certify_open_world_live_discovery as subject


def test_live_artifact_separates_candidates_from_authority(monkeypatch, tmp_path):
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({
        "prompts": [{"id": "novel-1", "prompt": "novel scientific workload"}],
    }), encoding="utf-8")
    plan = subject.build_case_research_plan(
        "novel scientific workload", allow_open_world=True,
    )
    monkeypatch.setattr(subject, "build_case_research_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(subject, "discover_open_world_publishers", lambda *args, **kwargs: {
        "receipts": [{
            "query_hash": "a" * 64, "external_call_dispatched": True,
            "execution_status": "completed",
        }] * 3,
        "candidates": [{
            "url": "https://publisher.example/requirements",
            "domain": "publisher.example", "title": "Requirements", "quality_score": 9,
        }],
        "provider_accounting": {"discovery_calls": 3, "external_calls": 3, "paid_calls": 0},
    })

    artifact = subject.certify(
        inputs=inputs, output=tmp_path / "artifact.json", search_url="http://search/",
    )

    assert artifact["certification_status"] == "passed"
    assert artifact["runs"][0]["candidate_origins"][0]["authority"] == (
        "candidate_only_not_accepted"
    )
    assert (tmp_path / "artifact.json.sha256").is_file()
