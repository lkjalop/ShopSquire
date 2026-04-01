from src.app.security.runtime_evidence_lab import run_runtime_evidence_swarm


def test_runtime_evidence_swarm_confirms_lolbin_with_parallel_agents():
    out = run_runtime_evidence_swarm(
        attack_hypothesis="lolbin_command_sequence",
        filename="steg-lolbin-demo.png",
    )
    assert out["supported"] is True
    assert out["claim_status"] == "observed"
    assert "T1105" in (out.get("mitre_attack") or [])
    assert "T1218.005" in (out.get("mitre_attack") or [])
    assert len(out.get("parallel_swarm") or []) >= 8
    assert "sandbox_detonation: process tree and child processes" in (out.get("runtime_evidence_present") or [])
    override = out.get("payload_analysis_override") or {}
    assert override.get("decode_path") == "runtime_confirmed_isolated_lab"


def test_runtime_evidence_swarm_returns_unsupported_for_unknown_hypothesis():
    out = run_runtime_evidence_swarm(attack_hypothesis="unknown", filename="benign.png")
    assert out["supported"] is False
    assert out["claim_status"] == "possible"
    assert out["mitre_attack"] == []
