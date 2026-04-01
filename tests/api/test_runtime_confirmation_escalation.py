from fastapi.testclient import TestClient

from src.app.main import create_app


def test_public_escalate_attaches_pending_runtime_confirmation(monkeypatch):
    import src.app.routers.escalation_room as escalation_room

    monkeypatch.setattr(escalation_room, "_allow_public_escalation", lambda _req: True)

    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/escalate",
        json={
            "trace_id": "trace-runtime-confirm-1",
            "reason": "queue_sandbox_detonation",
            "context": {
                "filename": "steg-lolbin-demo.png",
                "security_payload": {
                    "attack_hypothesis": "lolbin_command_sequence",
                    "suggested_next_step": "queue_sandbox_detonation",
                },
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    runtime_result = ((body.get("context") or {}).get("runtime_security_result") or {})
    assert runtime_result.get("supported") is True
    assert runtime_result.get("confirmation_tier") == "pending_runtime_evidence"
    assert runtime_result.get("claim_status") == "possible"
    assert runtime_result.get("mitre_attack") == []


def test_public_escalate_attaches_production_confirmation(monkeypatch):
    import src.app.routers.escalation_room as escalation_room
    import src.app.security.runtime_confirmation as runtime_confirmation

    monkeypatch.setattr(escalation_room, "_allow_public_escalation", lambda _req: True)
    monkeypatch.setattr(runtime_confirmation, "detonate_targets", lambda *_args, **_kwargs: {
        "provider": "private_sandbox",
        "malicious": True,
        "score": 0.98,
        "findings": [{"signal": "c2"}],
    })

    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/escalate",
        json={
            "trace_id": "trace-runtime-confirm-2",
            "reason": "queue_sandbox_detonation",
            "context": {
                "filename": "steg-lolbin-demo.png",
                "urls": ["https://dl.example.com/payload.bin"],
                "process_tree_events": [
                    {
                        "event_time": "2026-02-26T10:10:00Z",
                        "process_name": "powershell.exe",
                        "parent_process": "WINWORD.EXE",
                        "command_line": "powershell -enc AAAA",
                        "event_id": "proc-x1",
                    }
                ],
                "dns_proxy_lines": [
                    "2026-02-26T10:10:00Z action=allow src=10.0.0.5 dst=203.0.113.99 domain=download.example.com severity=high event_id=dns-x1",
                ],
                "firewall_syslog_lines": [
                    "2026-02-26T10:10:01Z action=allow src=10.0.0.5 dst=203.0.113.99 severity=high event_id=fw-x1",
                ],
                "security_payload": {
                    "attack_hypothesis": "lolbin_command_sequence",
                    "suggested_next_step": "queue_sandbox_detonation",
                },
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    runtime_result = ((body.get("context") or {}).get("runtime_security_result") or {})
    assert runtime_result.get("confirmation_tier") == "production_confirmed"
    assert runtime_result.get("claim_status") == "observed"
    assert "T1059.001" in (runtime_result.get("mitre_attack") or [])
