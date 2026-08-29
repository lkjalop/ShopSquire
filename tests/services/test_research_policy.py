import json

from src.app.services.research_policy import (
    active_research_policy, tenant_policy_auto_research_authorized,
)


def test_demo_policy_auto_authorizes_only_read_only_research(monkeypatch, tmp_path):
    path = tmp_path / "policies.json"
    path.write_text(json.dumps({
        "default_profile": "consent",
        "profiles": {
            "consent": {"external_research_enabled": True, "auto_authorize_read_only": False},
            "demo": {
                "external_research_enabled": True, "auto_authorize_read_only": True,
                "pasted_url_policy": "reviewed_canonical_origin_only",
                "max_provider_fanout": 99, "commerce_authority": "none",
            },
        },
    }), encoding="utf-8")
    monkeypatch.setenv("RESEARCH_POLICY_PATH", str(path))
    monkeypatch.setenv("RESEARCH_POLICY_PROFILE", "demo")
    monkeypatch.delenv("EXTERNAL_RESEARCH_AUTO_AUTHORIZED", raising=False)

    policy = active_research_policy()
    assert tenant_policy_auto_research_authorized() is True
    assert policy["profile_id"] == "demo"
    assert policy["max_provider_fanout"] == 3
    assert policy["pasted_url_policy"] == "reviewed_canonical_origin_only"
    assert policy["commerce_authority"] == "none"


def test_unknown_policy_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / "policies.json"
    path.write_text('{"profiles": {}}', encoding="utf-8")
    monkeypatch.setenv("RESEARCH_POLICY_PATH", str(path))
    monkeypatch.setenv("RESEARCH_POLICY_PROFILE", "missing")
    monkeypatch.delenv("EXTERNAL_RESEARCH_AUTO_AUTHORIZED", raising=False)

    policy = active_research_policy()
    assert policy["status"] == "unknown_profile_fail_closed"
    assert tenant_policy_auto_research_authorized() is False
