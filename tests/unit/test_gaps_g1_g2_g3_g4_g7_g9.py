"""Unit / lightweight API tests for gaps G1, G2, G3, G4, G7, G9.

All tests are designed to be fast, in-process, and low-memory:
- No full app startup (TestClient) except where strictly needed.
- Use SQLite in-memory or tmp_path so there's no leftover state.
- monkeypatch keeps external I/O from ever touching a network.
"""
import os
import io
import json
import time
import threading

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")


# ---------------------------------------------------------------------------
# G3: Cyrillic homoglyph detection survives NFKC normalisation
# ---------------------------------------------------------------------------

def test_cyrillic_homoglyph_in_from_domain_detected():
    """Cyrillic 'а' (U+0430) in sender domain must fire confusable_homoglyph_domain."""
    from src.app.security.email_security_rules import extract_indicators

    # 'а' here is CYRILLIC SMALL LETTER A (U+0430), not Latin 'a' (U+0061)
    cyrillic_from = "billing@ingrаm.com.au"
    email = {
        "from_addr": cyrillic_from,
        "reply_to": cyrillic_from,
        "subject": "Invoice attached",
        "body": "Please pay within 7 days.",
    }
    out = extract_indicators(email)
    types = [i["type"] for i in out["indicators"]]
    assert "confusable_homoglyph_domain" in types, (
        f"Expected confusable_homoglyph_domain for Cyrillic domain. Got: {types}"
    )


def test_pure_ascii_domain_no_homoglyph_false_positive():
    """Plain ASCII domain must NOT trigger confusable_homoglyph_domain."""
    from src.app.security.email_security_rules import extract_indicators

    email = {
        "from_addr": "billing@ingram.com.au",
        "reply_to": "billing@ingram.com.au",
        "subject": "Invoice",
        "body": "Details inside.",
    }
    out = extract_indicators(email)
    types = [i["type"] for i in out["indicators"]]
    assert "confusable_homoglyph_domain" not in types, (
        f"False-positive homoglyph on clean ASCII domain. Got: {types}"
    )


# ---------------------------------------------------------------------------
# G1: CrowdStrike OAuth token rotation
# ---------------------------------------------------------------------------

def test_crowdstrike_token_cached_after_first_request(monkeypatch):
    """Second call should reuse the cached bearer token (no second HTTP call)."""
    import src.app.security.telemetry_emit as te

    call_count = {"n": 0}

    class _MockResp:
        status_code = 200
        def json(self):
            return {"access_token": "cs-test-bearer", "expires_in": 1799}

    def _mock_post(url, **kw):
        call_count["n"] += 1
        return _MockResp()

    # Reset module-level cache
    te._cs_token = None
    te._cs_token_expiry = 0.0

    monkeypatch.setattr(te, "_cs_lock", threading.Lock())
    # Patch the check method on the live guard instance that the httpx hook closure holds
    from src.app.security import egress_allowlist as _ea
    live_guard = _ea.get_guard()
    monkeypatch.setattr(live_guard, "check", lambda url: None)

    # _get_crowdstrike_token uses httpx.post(), not httpx.Client()
    import httpx
    monkeypatch.setattr(httpx, "post", _mock_post)

    tok1 = te._get_crowdstrike_token("cid", "csec", "https://api.crowdstrike.com")
    tok2 = te._get_crowdstrike_token("cid", "csec", "https://api.crowdstrike.com")

    assert tok1 == "cs-test-bearer"
    assert tok2 == "cs-test-bearer"
    assert call_count["n"] == 1, f"Expected 1 HTTP call (cached), got {call_count['n']}"


def test_crowdstrike_token_refreshed_when_expired(monkeypatch):
    """Token with expiry in the past should trigger a new request."""
    import src.app.security.telemetry_emit as te

    call_count = {"n": 0}

    def _mock_post(url, **kw):
        call_count["n"] += 1
        class _Resp:
            status_code = 200
            def json(self_r):
                return {"access_token": f"tok-{call_count['n']}", "expires_in": 1799}
        return _Resp()

    te._cs_token = "stale-token"
    te._cs_token_expiry = time.monotonic() - 10  # already expired

    # Patch the check method on the live guard instance that the httpx hook closure holds
    from src.app.security import egress_allowlist as _ea
    live_guard = _ea.get_guard()
    monkeypatch.setattr(live_guard, "check", lambda url: None)

    # _get_crowdstrike_token uses httpx.post(), not httpx.Client()
    import httpx
    monkeypatch.setattr(httpx, "post", _mock_post)

    tok = te._get_crowdstrike_token("cid", "csec", "https://api.crowdstrike.com")
    assert tok is not None
    assert call_count["n"] == 1, "Should have re-fetched after expiry"


def test_emit_to_crowdstrike_noop_when_no_envvars(monkeypatch):
    """emit_to_crowdstrike must be silent when no env vars are set."""
    import src.app.security.telemetry_emit as te

    monkeypatch.delenv("CROWDSTRIKE_CLIENT_ID", raising=False)
    monkeypatch.delenv("CROWDSTRIKE_CLIENT_SECRET", raising=False)

    posted = {"hit": False}

    def _bad_post(*a, **kw):
        posted["hit"] = True

    monkeypatch.setattr(te, "_post_json", _bad_post)

    te.emit_to_crowdstrike({"event_type": "test"})
    # Allow background thread to run a moment
    time.sleep(0.05)
    assert not posted["hit"], "Should not attempt HTTP when envvars absent"


# ---------------------------------------------------------------------------
# G2: Email multipart upload endpoint
# ---------------------------------------------------------------------------

def test_email_upload_eml_endpoint(tmp_path, monkeypatch):
    """POST /api/v1/email_security/upload with a .eml file returns evaluation shape."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/g2.db")
    monkeypatch.setenv("DATABASE_URL_RO", f"sqlite+pysqlite:///{tmp_path}/g2.db")

    from fastapi.testclient import TestClient
    from src.app.main import create_app

    # Minimal RFC-822 .eml
    eml_bytes = (
        b"From: attacker@micros0ft.com\r\n"
        b"To: victim@corp.com\r\n"
        b"Subject: Urgent invoice\r\n"
        b"Message-ID: <upload-test@x>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Please wire money immediately.\r\n"
    )
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/email_security/upload",
        files={"file": ("invoice.eml", io.BytesIO(eml_bytes), "message/rfc822")},
        headers={"x-api-key": "local-owner-key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Upload endpoint returns {status, filename, file_type, size_bytes, result: {...}}
    assert body.get("status") == "ok"
    result = body.get("result") or {}
    assert "route" in result or "verdict_action" in result or "indicators" in result, (
        f"Unexpected result shape: {list(result.keys())}"
    )


def test_email_upload_rejects_bad_extension(tmp_path, monkeypatch):
    """Upload of an unsupported extension (.txt) must return 400."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/g2b.db")
    monkeypatch.setenv("DATABASE_URL_RO", f"sqlite+pysqlite:///{tmp_path}/g2b.db")

    from fastapi.testclient import TestClient
    from src.app.main import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/email_security/upload",
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
        headers={"x-api-key": "local-owner-key"},
    )
    # 400 or 415 are both acceptable rejections for unsupported extension
    assert resp.status_code in (400, 415), f"Expected 400/415 for .txt upload, got {resp.status_code}"


# ---------------------------------------------------------------------------
# G4: Session scrollback endpoint
# ---------------------------------------------------------------------------

def test_session_decisions_empty_session(tmp_path, monkeypatch):
    """GET /session/{id} for unknown session returns count=0, no error."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/g4.db")
    monkeypatch.setenv("DATABASE_URL_RO", f"sqlite+pysqlite:///{tmp_path}/g4.db")

    from fastapi.testclient import TestClient
    from src.app.main import create_app

    client = TestClient(create_app())
    resp = client.get(
        "/api/v1/decisions/session/unknown-session-xyz",
        headers={"x-api-key": "local-merchant-key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == "unknown-session-xyz"
    assert body["count"] == 0
    assert body["decisions"] == []


def test_session_decisions_fallback_input_data(tmp_path, monkeypatch):
    """Session scrollback works via input_data JSON fallback when column absent."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/g4b.db")
    monkeypatch.setenv("DATABASE_URL_RO", f"sqlite+pysqlite:///{tmp_path}/g4b.db")

    from sqlalchemy import create_engine, text
    from src.app.models.db import set_engine

    db_url = f"sqlite+pysqlite:///{tmp_path}/g4b.db"
    eng = create_engine(db_url, connect_args={"check_same_thread": False})
    set_engine(eng)

    # Create minimal decision_logs table WITHOUT session_id column
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS decision_logs ("
            "id TEXT PRIMARY KEY, agent_name TEXT, valid_from TEXT, valid_to TEXT, "
            "system_from TEXT, system_to TEXT, input_data TEXT, retrieved_context TEXT, "
            "proposed_action TEXT, policy_version TEXT, execution_status TEXT"
            ")"
        ))
        conn.execute(text(
            "INSERT INTO decision_logs (id, agent_name, valid_from, input_data, execution_status) "
            "VALUES ('row-1', 'TestAgent', '2026-01-01', :inp, 'created')"
        ), {"inp": json.dumps({"session_id": "sess-abc", "query": "hello"})})

    from fastapi.testclient import TestClient
    from src.app.main import create_app

    client = TestClient(create_app())
    resp = client.get(
        "/api/v1/decisions/session/sess-abc",
        headers={"x-api-key": "local-merchant-key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == "sess-abc"
    assert body["count"] >= 1, f"Expected ≥1 result, got {body}"


# ---------------------------------------------------------------------------
# G7: CyberStash + generic EDR dispatch
# ---------------------------------------------------------------------------

def test_cyberstash_target_dispatched(monkeypatch):
    """emit_security_handoff should hit cyberstash target when env is set."""
    import src.app.security.siem_adapter as sa

    posted = []

    def _fake_post_json(url, headers, payload, timeout_s=4.0):
        posted.append({"url": url, "headers": headers})
        return True, 200, None

    monkeypatch.setattr(sa, "_post_json", _fake_post_json)
    monkeypatch.setenv("CYBERSTASH_INGEST_URL", "https://cs.example.com/ingest")
    monkeypatch.setenv("CYBERSTASH_API_KEY", "cskey")
    # Disable all other targets
    for envvar in ["SIEM_WEBHOOK_URL", "SPLUNK_HEC_URL", "ELASTIC_SECURITY_EVENTS_URL",
                   "SENTINEL_INGEST_URL", "CROWDSTRIKE_INGEST_URL", "CSPM_INGEST_URL",
                   "GENERIC_EDR_INGEST_URL"]:
        monkeypatch.delenv(envvar, raising=False)

    sa.emit_security_handoff({"decision_id": "d1", "trace_id": "t1", "tenant_id": "tt"})

    urls = [p["url"] for p in posted]
    assert any("cs.example.com" in u for u in urls), f"cyberstash URL not called. Got: {urls}"
    hit = next(p for p in posted if "cs.example.com" in p["url"])
    assert hit["headers"].get("x-api-key") == "cskey"


def test_generic_edr_target_dispatched(monkeypatch):
    """emit_security_handoff should dispatch generic_edr when env is set."""
    import src.app.security.siem_adapter as sa

    posted = []

    def _fake_post_json(url, headers, payload, timeout_s=4.0):
        posted.append({"url": url, "headers": headers})
        return True, 200, None

    monkeypatch.setattr(sa, "_post_json", _fake_post_json)
    monkeypatch.setenv("GENERIC_EDR_INGEST_URL", "https://edr.example.com/events")
    monkeypatch.setenv("GENERIC_EDR_API_KEY", "edrkey")
    monkeypatch.setenv("GENERIC_EDR_VENDOR", "sentinelone")
    for envvar in ["SIEM_WEBHOOK_URL", "SPLUNK_HEC_URL", "ELASTIC_SECURITY_EVENTS_URL",
                   "SENTINEL_INGEST_URL", "CROWDSTRIKE_INGEST_URL", "CSPM_INGEST_URL",
                   "CYBERSTASH_INGEST_URL"]:
        monkeypatch.delenv(envvar, raising=False)

    sa.emit_security_handoff({"decision_id": "d2", "trace_id": "t2", "tenant_id": "tt"})

    urls = [p["url"] for p in posted]
    assert any("edr.example.com" in u for u in urls), f"EDR URL not called. Got: {urls}"
    hit = next(p for p in posted if "edr.example.com" in p["url"])
    assert hit["headers"].get("Authorization") == "Bearer edrkey"


# ---------------------------------------------------------------------------
# G9: Threat intel refresh triggered on high/critical escalation
# ---------------------------------------------------------------------------

def test_threat_intel_sync_submitted_on_escalation(monkeypatch):
    """escalation_agent step must call submit_task('threat_intel_sync') for high severity."""
    import src.app.security.supply_chain_harness as sch

    submitted = []

    def _fake_submit(task_name, payload=None):
        submitted.append({"task": task_name, "payload": payload})

    # Monkeypatch the import that happens inside the function
    import sys
    fake_tr = type(sys)("fake_task_runner")
    fake_tr.submit_task = _fake_submit
    monkeypatch.setitem(sys.modules, "src.app.workers.task_runner", fake_tr)

    scenario = {
        "scenario_id": "sim-001",
        "tenant_id": "tenant-x",
        "human_escalation_expected": True,
        "risk_band": "high",
    }
    context = {"risk_analysis": {"severity": "high"}}

    # Find the escalation_agent link from _DEFAULT_AGENT_CHAIN
    import copy
    agent = copy.deepcopy(next(a for a in sch._DEFAULT_AGENT_CHAIN if a.agent_id == "escalation_agent"))
    # Simulate step
    sch._run_agent_step(agent, scenario, context, trace_id="tr-test", step_counter=[0])

    task_names = [s["task"] for s in submitted]
    assert "threat_intel_sync" in task_names, (
        f"threat_intel_sync not submitted. Got: {task_names}"
    )
    sync = next(s for s in submitted if s["task"] == "threat_intel_sync")
    assert sync["payload"].get("tenant_id") == "tenant-x"
    assert "escalation" in sync["payload"].get("reason", "")


def test_threat_intel_sync_not_submitted_below_threshold(monkeypatch):
    """escalation_agent must NOT submit threat_intel_sync for low severity."""
    import src.app.security.supply_chain_harness as sch
    import sys

    submitted = []

    fake_tr = type(sys)("fake_task_runner2")
    fake_tr.submit_task = lambda *a, **kw: submitted.append(a)
    monkeypatch.setitem(sys.modules, "src.app.workers.task_runner", fake_tr)

    scenario = {
        "scenario_id": "sim-002",
        "tenant_id": "tenant-y",
        "human_escalation_expected": False,
        "risk_band": "low",
    }
    context = {"risk_analysis": {"severity": "low"}}

    import copy
    agent = copy.deepcopy(next(a for a in sch._DEFAULT_AGENT_CHAIN if a.agent_id == "escalation_agent"))
    sch._run_agent_step(agent, scenario, context, trace_id="tr-test2", step_counter=[0])

    assert not submitted, f"Should not submit task for low severity. Got: {submitted}"
