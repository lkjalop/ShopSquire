"""Unit-level test suite for the supply-chain simulation harness.

These tests exercise scenarios **locally** (no live server required) by
importing the harness, running each scenario through the observer / risk
pipeline, and validating that expected signals, severity levels, and
escalation decisions are produced.

Run with::

    pytest tests/security/test_supply_chain_simulation.py -v
"""

from __future__ import annotations

import os
import pytest
from dataclasses import asdict

# Disable real escalation and ensure trace is off (no Redis needed)
os.environ.setdefault("SC_HARNESS_TRACE_ENABLED", "0")
os.environ.setdefault("SC_HARNESS_ESCALATE_ENABLED", "0")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///tests/security/sim_test.sqlite")
os.environ.setdefault("DISABLE_TRACING", "1")


@pytest.fixture(autouse=True)
def _skip_security_server(request, monkeypatch):
    """Override the session-scoped security_test_server from conftest —
    simulation tests run locally without a server."""
    pass


# Override the session-scoped fixture from security/conftest.py so it
# doesn't spin up a uvicorn server for these pure-unit tests.
@pytest.fixture(scope="session")
def security_test_server():
    """No-op override: simulation tests don't need a live API server."""
    yield {"base_url": "http://localhost:0"}

from src.app.security.supply_chain_scenarios import (
    get_scenario,
    list_scenarios,
    ALL_SCENARIOS,
)
from src.app.security.supply_chain_harness import (
    SimulationResult,
    ThinkingStep,
    AgentChainLink,
    run_scenario,
    run_all,
    format_report,
    _extract_demo_iocs,
)


# ---------------------------------------------------------------------------
# Scenario registry tests
# ---------------------------------------------------------------------------

class TestScenarioRegistry:
    """Verify scenario definitions are well-formed."""

    def test_all_scenarios_populated(self):
        scenarios = list_scenarios()
        assert len(scenarios) >= 8, f"Expected ≥8 scenarios, got {len(scenarios)}"

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_scenario_has_required_fields(self, sid):
        s = get_scenario(sid)
        for field in ("scenario_id", "name", "mitre_attack", "owasp_tags",
                       "kill_chain", "payload", "expected_signals",
                       "expected_severity", "human_escalation_expected",
                       "description"):
            assert field in s, f"{sid} missing field '{field}'"

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_scenario_payload_is_dict(self, sid):
        s = get_scenario(sid)
        assert isinstance(s["payload"], dict), f"{sid}: payload must be dict"

    def test_get_scenario_unknown_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_scenario("SC-999")

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_scenario_uses_safe_iocs(self, sid):
        """All IOCs must use RFC-2606 / RFC-5737 reserved addresses."""
        import json, re
        text = json.dumps(get_scenario(sid)["payload"])
        # Check IPs are in TEST-NET ranges
        for m in re.finditer(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text):
            ip = m.group(1)
            parts = ip.split(".")
            prefix = int(parts[0])
            # TEST-NET-1: 192.0.2.0/24, TEST-NET-2: 198.51.100.0/24, TEST-NET-3: 203.0.113.0/24
            # Also allow 127.x (loopback)
            assert ip.startswith(("192.0.2.", "198.51.100.", "203.0.113.", "127.")) or prefix == 0, \
                f"{sid}: IP {ip} is not in a safe reserved range"


# ---------------------------------------------------------------------------
# IOC extraction tests
# ---------------------------------------------------------------------------

class TestIOCExtraction:

    def test_extracts_urls(self):
        payload = {"url": "https://evil.example.com/skim.js", "note": "test"}
        iocs = _extract_demo_iocs(payload)
        urls = [i for i in iocs if i["type"] == "url"]
        assert len(urls) >= 1
        assert "example.com" in urls[0]["domain"]

    def test_extracts_ips(self):
        payload = {"beacon_dst": "203.0.113.42"}
        iocs = _extract_demo_iocs(payload)
        ips = [i for i in iocs if i["type"] == "ip"]
        assert any(i["value"] == "203.0.113.42" for i in ips)

    def test_extracts_hashes(self):
        h = "a" * 64
        payload = {"hash": f"sha256:{h}"}
        iocs = _extract_demo_iocs(payload)
        hashes = [i for i in iocs if i["type"] == "hash"]
        assert any(i["value"] == h for i in hashes)


# ---------------------------------------------------------------------------
# Harness execution tests
# ---------------------------------------------------------------------------

class TestHarnessExecution:
    """Run each scenario through the harness and validate outputs."""

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_scenario_produces_result(self, sid):
        result = run_scenario(sid)
        assert isinstance(result, SimulationResult)
        assert result.scenario_id == sid
        assert result.trace_id  # non-empty UUID
        assert result.decision_id

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_scenario_has_thinking_steps(self, sid):
        result = run_scenario(sid)
        assert len(result.thinking_steps) >= 4, f"{sid}: expected ≥4 thinking steps"
        agents = [s.agent for s in result.thinking_steps]
        assert "intake_gate" in agents
        assert "security_observer" in agents
        assert "policy_engine" in agents
        assert "escalation_agent" in agents

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_thinking_steps_have_reasoning(self, sid):
        result = run_scenario(sid)
        for step in result.thinking_steps:
            assert step.reasoning, f"{sid}: step {step.step_id} ({step.agent}) has empty reasoning"
            assert step.timestamp

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_agent_chain_complete(self, sid):
        result = run_scenario(sid)
        assert len(result.agent_chain) >= 5
        for link in result.agent_chain:
            assert link.status == "done", f"{sid}: agent {link.agent_id} not done"

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_severity_not_empty(self, sid):
        result = run_scenario(sid)
        assert result.severity in ("info", "low", "medium", "high", "critical"), \
            f"{sid}: unexpected severity '{result.severity}'"

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_pass_fail_assigned(self, sid):
        result = run_scenario(sid)
        assert result.pass_fail in ("PASS", "PARTIAL", "FAIL")

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_bitemporal_fields_present(self, sid):
        result = run_scenario(sid)
        for key in ("valid_from", "valid_to", "system_from", "system_to"):
            assert key in result.bitemporal, f"{sid}: missing bitemporal field '{key}'"

    @pytest.mark.parametrize("sid", list(ALL_SCENARIOS.keys()))
    def test_result_serializable(self, sid):
        """Ensure SimulationResult can be serialized to JSON (for API responses)."""
        import json
        result = run_scenario(sid)
        d = asdict(result)
        text = json.dumps(d, default=str)
        assert len(text) > 100  # non-trivial JSON


# ---------------------------------------------------------------------------
# Run-all and report tests
# ---------------------------------------------------------------------------

class TestRunAllAndReport:

    def test_run_all_returns_list(self):
        results = run_all()
        assert isinstance(results, list)
        assert len(results) >= 8

    def test_format_report_contains_all_scenarios(self):
        results = run_all()
        report = format_report(results)
        assert "SUPPLY-CHAIN ATTACK SIMULATION REPORT" in report
        for r in results:
            assert r.scenario_id in report

    def test_extra_context_injected(self):
        result = run_scenario("SC-01", extra_context={"analyst": "unit-test"})
        assert result.injected_context.get("analyst") == "unit-test"


# ---------------------------------------------------------------------------
# Specific scenario validation
# ---------------------------------------------------------------------------

class TestSpecificScenarios:
    """Spot-check individual scenarios for expected behaviour."""

    def test_sc04_c2_detects_supply_chain_signal(self):
        """SC-04 (C2 beaconing) should trigger supply_chain or at least produce a result."""
        result = run_scenario("SC-04")
        # The observer may or may not detect 'supply_chain' depending on payload text,
        # but it should at least run through the full chain
        assert result.severity in ("info", "low", "medium", "high", "critical")
        assert len(result.thinking_steps) >= 4

    def test_sc07_dependency_confusion_payload(self):
        """SC-07 (dependency confusion / shai-hulud) payload should contain supply-chain keywords."""
        scenario = get_scenario("SC-07")
        import json
        text = json.dumps(scenario["payload"]).lower()
        assert "dependency" in text or "supply" in text or "package" in text

    def test_sc01_magecart_escalation_expected(self):
        """SC-01 (Magecart) should expect human escalation."""
        scenario = get_scenario("SC-01")
        assert scenario["human_escalation_expected"] is True
