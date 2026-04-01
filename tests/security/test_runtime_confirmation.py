from src.app.security.runtime_confirmation import confirm_runtime_evidence


def test_runtime_confirmation_stays_pending_without_real_provider():
    out = confirm_runtime_evidence(
        attack_hypothesis="c2_beacon",
        context={
            "dns_proxy_lines": ["2026-02-26T10:10:00Z action=allow domain=c2.example.com dst=203.0.113.99 event_id=dns-1"],
        },
    )
    assert out["confirmation_tier"] == "pending_runtime_evidence"
    assert out["mitre_attack"] == []
    assert out["claim_status"] == "possible"


def test_runtime_confirmation_promotes_with_real_telemetry(monkeypatch):
    import src.app.security.runtime_confirmation as rc

    monkeypatch.setattr(rc, "detonate_targets", lambda *_args, **_kwargs: {
        "provider": "private_sandbox",
        "malicious": True,
        "score": 0.99,
        "findings": [{"signal": "beacon"}],
    })
    out = confirm_runtime_evidence(
        attack_hypothesis="c2_beacon",
        context={
            "urls": ["https://c2.example.com"],
            "process_tree_events": [
                {
                    "process_name": "svchost.exe",
                    "parent_process": "services.exe",
                    "command_line": "svchost.exe -k beacon",
                }
            ],
            "dns_proxy_lines": [
                "2026-02-26T10:10:00Z action=allow domain=c2.example.com dst=203.0.113.99 event_id=dns-1"
            ],
            "firewall_syslog_lines": [
                "2026-02-26T10:10:01Z action=allow src=10.0.0.5 dst=203.0.113.99 severity=high event_id=fw-1"
            ],
        },
    )
    assert out["confirmation_tier"] == "production_confirmed"
    assert out["claim_status"] == "observed"
    assert "T1071.001" in (out.get("mitre_attack") or [])


def test_fileless_runtime_confirmation_requires_memory_telemetry(monkeypatch):
    import src.app.security.runtime_confirmation as rc

    monkeypatch.setattr(rc, "detonate_targets", lambda *_args, **_kwargs: {
        "provider": "private_sandbox",
        "malicious": True,
        "score": 0.99,
        "findings": [{"signal": "fileless"}],
    })
    out = confirm_runtime_evidence(
        attack_hypothesis="fileless_attack",
        context={
            "urls": ["https://dl.example.com/payload.bin"],
            "process_tree_events": [
                {
                    "process_name": "powershell.exe",
                    "parent_process": "WINWORD.EXE",
                    "command_line": "powershell -enc AAAA",
                }
            ],
            "edr_memory_events": [
                {
                    "process_name": "powershell.exe",
                    "detection_name": "ProcessTampering",
                    "memory_strings": "CreateRemoteThread reflective shellcode",
                }
            ],
        },
    )
    assert out["confirmation_tier"] == "production_confirmed"
    assert "edr_memory_forensics: runtime memory or process-tampering evidence confirmed" in (out.get("runtime_evidence_present") or [])
