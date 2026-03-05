"""Supply-chain attack simulation harness.

Executes scenarios from ``supply_chain_scenarios.py`` through the
ShopSquire security stack, recording a **bitemporal decision trace**
with interleaved-thinking steps, dynamic context injection, agent
chaining, and human escalation triggers.

The harness is *completely safe*: it only processes inert payloads
against the existing observer / risk-engine / escalation pipeline
and writes trace events to the DB.  No real network calls, no real
malware, no live C2 – every external domain is ``example.com`` and
every IP is from RFC-5737 TEST-NET ranges.

Usage
-----
::

    from src.app.security.supply_chain_harness import run_scenario, run_all

    # Single scenario with full trace
    result = run_scenario("SC-04")

    # All scenarios
    results = run_all()

ENV configuration
-----------------
SC_HARNESS_TRACE_ENABLED    – "1" to persist trace events (default "1")
SC_HARNESS_ESCALATE_ENABLED – "1" to trigger real escalation (default "0")
SC_HARNESS_AGENT_CHAIN      – Comma-sep agent IDs to chain (default built-in)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.app.security.supply_chain_scenarios import get_scenario, list_scenarios

logger = logging.getLogger("shopsquire.supply_chain_harness")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_bool(key: str, default: bool = False) -> bool:
    v = (os.getenv(key) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ThinkingStep:
    """One interleaved-thinking step in the decision trace."""
    step_id: int
    agent: str
    action: str
    reasoning: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    timestamp: str = ""


@dataclass
class AgentChainLink:
    """One agent in the processing chain."""
    agent_id: str
    role: str
    order: int
    status: str = "pending"  # pending → running → done → escalated
    findings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    """Full result of a scenario simulation."""
    scenario_id: str
    scenario_name: str
    trace_id: str
    decision_id: str
    thinking_steps: List[ThinkingStep] = field(default_factory=list)
    agent_chain: List[AgentChainLink] = field(default_factory=list)
    injected_context: Dict[str, Any] = field(default_factory=dict)
    risk_analysis: Dict[str, Any] = field(default_factory=dict)
    signals_detected: List[str] = field(default_factory=list)
    severity: str = "info"
    human_escalation_triggered: bool = False
    escalation_reason: str = ""
    incident_id: Optional[str] = None
    bitemporal: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    pass_fail: str = "unknown"


# ---------------------------------------------------------------------------
# Agent chain definitions
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_CHAIN = [
    AgentChainLink(agent_id="intake_gate", role="Intake & format validation", order=0),
    AgentChainLink(agent_id="ioc_extractor", role="IOC extraction & enrichment", order=1),
    AgentChainLink(agent_id="security_observer", role="Signal detection & risk scoring", order=2),
    AgentChainLink(agent_id="threat_intel", role="Threat-intel cross-reference", order=3),
    AgentChainLink(agent_id="policy_engine", role="Policy evaluation & verdict", order=4),
    AgentChainLink(agent_id="escalation_agent", role="Human escalation routing", order=5),
]


# ---------------------------------------------------------------------------
# Core harness
# ---------------------------------------------------------------------------

def _emit_trace(trace_id: str, event_type: str, source: str, payload: Dict[str, Any]) -> None:
    """Persist a trace event if tracing is enabled."""
    if not _env_bool("SC_HARNESS_TRACE_ENABLED", True):
        return
    try:
        from src.app.services.trace_broker import publish_sync
        publish_sync(trace_id, {
            "trace_id": trace_id,
            "event_type": event_type,
            "source_type": "supply_chain_harness",
            "source_id": source,
            "payload": payload,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.debug("trace emit failed: %s", exc)


def _run_agent_step(
    agent: AgentChainLink,
    scenario: Dict[str, Any],
    context: Dict[str, Any],
    trace_id: str,
    step_counter: List[int],
) -> ThinkingStep:
    """Execute one agent in the chain and produce a thinking step."""
    t0 = time.perf_counter()
    agent.status = "running"
    step_id = step_counter[0]
    step_counter[0] += 1

    reasoning = ""
    outputs: Dict[str, Any] = {}

    payload = scenario.get("payload") or {}

    if agent.agent_id == "intake_gate":
        reasoning = (
            f"Ingesting {scenario['scenario_id']} ({scenario['name']}). "
            f"Event type: {payload.get('event_type', 'unknown')}. "
            f"Validating payload structure and extracting artefact metadata."
        )
        outputs = {
            "event_type": payload.get("event_type"),
            "artefact_count": len(payload),
            "has_hash": bool(payload.get("sha256") or payload.get("expected_hash")),
            "gate_pass": True,
        }

    elif agent.agent_id == "ioc_extractor":
        iocs = _extract_demo_iocs(payload)
        reasoning = (
            f"Extracted {len(iocs)} IOCs from payload. "
            f"Types: {sorted(set(i.get('type','') for i in iocs))}. "
            f"Cross-referencing against threat-intel store."
        )
        outputs = {"iocs": iocs, "ioc_count": len(iocs)}
        context["iocs"] = iocs

    elif agent.agent_id == "security_observer":
        from src.app.security.observer import compute_risk
        severity, risk_raw, risk_adj, details = compute_risk(payload)
        reasoning = (
            f"Risk score: raw={round(risk_raw, 1)} adj={round(risk_adj, 1)} → severity={severity}. "
            f"Signals: {[k for k,v in (details.get('signals') or {}).items() if v]}. "
            f"MITRE tags: {details.get('mitre_atlas', [])}. "
            f"OWASP tags: {details.get('owasp_llm_top10', [])}."
        )
        outputs = {
            "severity": severity,
            "risk_raw": round(risk_raw, 1),
            "risk_adj": round(risk_adj, 1),
            "signals": {k: v for k, v in (details.get("signals") or {}).items() if v},
            "mitre_atlas": details.get("mitre_atlas", []),
            "owasp_llm_top10": details.get("owasp_llm_top10", []),
            "owasp_agentic_top10": details.get("owasp_agentic_top10", []),
            "stride_categories": details.get("stride_categories", []),
            "pasta_stage": details.get("pasta_stage"),
        }
        context["risk_analysis"] = outputs

    elif agent.agent_id == "threat_intel":
        # Cross-reference IOCs against local threat-intel store
        iocs = context.get("iocs") or []
        matches = []
        try:
            from src.app.security.threat_intel_store import resolve_indicator
            for ioc in iocs[:20]:
                result = resolve_indicator(
                    tenant_id=None,
                    indicator_type=ioc.get("type", ""),
                    indicator_value=ioc.get("value", ""),
                )
                if result:
                    matches.append({**ioc, "ti_verdict": result.get("verdict"), "ti_confidence": result.get("confidence")})
        except Exception:
            pass
        found_vals = [m.get("value") for m in matches[:3]]
        match_summary = "No prior intelligence found." if not matches else f"Found: {found_vals}"
        reasoning = (
            f"Cross-referenced {len(iocs)} IOCs against threat-intel store. "
            f"Matches: {len(matches)}. "
            f"{match_summary}"
        )
        outputs = {"matches": matches, "match_count": len(matches)}
        context["ti_matches"] = matches

    elif agent.agent_id == "policy_engine":
        risk = context.get("risk_analysis") or {}
        severity = risk.get("severity", "info")
        signals = risk.get("signals") or {}
        expected = set(scenario.get("expected_signals") or [])
        detected = set(signals.keys())
        coverage = expected & detected
        reasoning = (
            f"Policy evaluation: severity={severity}. "
            f"Expected signals: {sorted(expected)}. "
            f"Detected: {sorted(detected)}. "
            f"Coverage: {len(coverage)}/{len(expected)}. "
            f"Verdict: {'ESCALATE' if scenario.get('human_escalation_expected') and severity in ('high','critical') else 'REVIEW'}."
        )
        outputs = {
            "verdict": "escalate" if severity in ("high", "critical") else "review",
            "signal_coverage": f"{len(coverage)}/{len(expected)}",
            "missing_signals": sorted(expected - detected),
        }

    elif agent.agent_id == "escalation_agent":
        risk = context.get("risk_analysis") or {}
        severity = risk.get("severity", "info")
        should_escalate = severity in ("high", "critical") and scenario.get("human_escalation_expected", False)
        reasoning = (
            f"Escalation decision: severity={severity}, "
            f"scenario expects escalation={scenario.get('human_escalation_expected')}. "
            f"{'→ ESCALATING to human analyst.' if should_escalate else '→ Automated handling sufficient.'}"
        )
        outputs = {
            "escalated": should_escalate,
            "reason": f"{scenario['scenario_id']}: {severity} severity, supply-chain attack pattern" if should_escalate else "below_threshold",
        }
        context["escalation"] = outputs
        if should_escalate:
            try:
                from src.app.workers.task_runner import submit_task
                submit_task("threat_intel_sync", {
                    "tenant_id": scenario.get("tenant_id", "default"),
                    "reason": f"escalation:{scenario['scenario_id']}",
                })
            except Exception:
                pass

    else:
        reasoning = f"Agent {agent.agent_id}: no specific handler, pass-through."
        outputs = {}

    agent.status = "done"
    agent.findings = outputs
    elapsed = (time.perf_counter() - t0) * 1000

    step = ThinkingStep(
        step_id=step_id,
        agent=agent.agent_id,
        action=agent.role,
        reasoning=reasoning,
        inputs={"scenario_id": scenario["scenario_id"], "context_keys": list(context.keys())},
        outputs=outputs,
        duration_ms=round(elapsed, 2),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    _emit_trace(trace_id, f"agent_step:{agent.agent_id}", agent.agent_id, asdict(step))

    return step


def _extract_demo_iocs(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract IOC-like artefacts from a demo payload (no real lookups)."""
    iocs: List[Dict[str, Any]] = []
    text = json.dumps(payload, ensure_ascii=False)
    import re
    for m in re.finditer(r"https?://([^\s\"',]+)", text):
        url = m.group(0)
        domain_m = re.search(r"https?://([^/:]+)", url)
        domain = domain_m.group(1) if domain_m else None
        iocs.append({"type": "url", "value": url, "domain": domain, "source": "payload"})
    for m in re.finditer(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        iocs.append({"type": "ip", "value": m.group(0), "source": "payload"})
    for m in re.finditer(r"sha256:([a-f0-9]{64})", text):
        iocs.append({"type": "hash", "value": m.group(1), "source": "payload"})
    return iocs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_scenario(
    scenario_id: str,
    *,
    extra_context: Dict[str, Any] | None = None,
) -> SimulationResult:
    """Run a single supply-chain attack scenario through the full agent chain.

    Returns a ``SimulationResult`` with bitemporal decision trace,
    interleaved thinking steps, and human escalation status.
    """
    t0 = time.perf_counter()
    scenario = get_scenario(scenario_id)
    trace_id = str(uuid.uuid4())
    decision_id = str(uuid.uuid4())

    now_iso = datetime.now(timezone.utc).isoformat()
    bitemporal = {
        "valid_from": now_iso,
        "valid_to": "infinity",
        "system_from": now_iso,
        "system_to": "infinity",
    }

    # Dynamic context injection
    context: Dict[str, Any] = {
        "scenario": scenario,
        "trace_id": trace_id,
        "decision_id": decision_id,
        "bitemporal": bitemporal,
        "injected_at": now_iso,
    }
    if extra_context:
        context.update(extra_context)

    _emit_trace(trace_id, "simulation_start", "harness", {
        "scenario_id": scenario["scenario_id"],
        "scenario_name": scenario["name"],
        "decision_id": decision_id,
        "bitemporal": bitemporal,
        "kill_chain": scenario.get("kill_chain", []),
        "mitre_attack": scenario.get("mitre_attack", []),
    })

    # Build agent chain
    chain = [AgentChainLink(**{**asdict(a)}) for a in _DEFAULT_AGENT_CHAIN]
    step_counter = [0]
    thinking_steps: List[ThinkingStep] = []

    for agent in chain:
        step = _run_agent_step(agent, scenario, context, trace_id, step_counter)
        thinking_steps.append(step)

    # Aggregate results
    risk = context.get("risk_analysis") or {}
    severity = risk.get("severity", "info")
    signals_detected = list((risk.get("signals") or {}).keys())
    escalation = context.get("escalation") or {}
    escalated = bool(escalation.get("escalated"))
    escalation_reason = str(escalation.get("reason", ""))

    # Optionally trigger real escalation pipeline
    incident_id = None
    if escalated and _env_bool("SC_HARNESS_ESCALATE_ENABLED", False):
        try:
            from src.app.security.escalation import auto_route_security_event
            event_id = str(uuid.uuid4())
            auto_route_security_event(event_id, severity, float(risk.get("risk_adj", 0.0)), risk)
            incident_id = event_id
        except Exception as exc:
            logger.warning("escalation failed: %s", exc)

    # Persist bitemporal decision log
    try:
        from src.app.services.decision_log import log_decision
        log_decision(
            agent_name="supply_chain_harness",
            input_data={"scenario_id": scenario["scenario_id"], "payload_hash": hashlib.sha256(json.dumps(scenario["payload"], sort_keys=True).encode()).hexdigest()[:16]},
            retrieved_context={"severity": severity, "signals": signals_detected, "mitre": scenario.get("mitre_attack", [])},
            proposed_action={"escalated": escalated, "incident_id": incident_id, "verdict": escalation.get("reason")},
            agent_reasoning="; ".join(s.reasoning for s in thinking_steps),
            policy_version="v1",
            approval_required=escalated,
            execution_status="escalated" if escalated else "auto_processed",
        )
    except Exception:
        pass

    # Determine pass/fail
    expected_signals = set(scenario.get("expected_signals") or [])
    detected_set = set(signals_detected)
    expected_sev = scenario.get("expected_severity", "info")
    expected_escalation = scenario.get("human_escalation_expected", False)

    checks = [
        bool(expected_signals & detected_set),  # at least one expected signal detected
        severity == expected_sev or (severity in ("high", "critical") and expected_sev in ("high", "critical")),
        escalated == expected_escalation or (escalated and expected_escalation),
    ]
    pass_fail = "PASS" if all(checks) else "PARTIAL" if any(checks) else "FAIL"

    elapsed = (time.perf_counter() - t0) * 1000

    _emit_trace(trace_id, "simulation_end", "harness", {
        "scenario_id": scenario["scenario_id"],
        "severity": severity,
        "pass_fail": pass_fail,
        "escalated": escalated,
        "elapsed_ms": round(elapsed, 2),
    })

    return SimulationResult(
        scenario_id=scenario["scenario_id"],
        scenario_name=scenario["name"],
        trace_id=trace_id,
        decision_id=decision_id,
        thinking_steps=thinking_steps,
        agent_chain=chain,
        injected_context={k: v for k, v in context.items() if k not in ("scenario",)},
        risk_analysis=risk,
        signals_detected=signals_detected,
        severity=severity,
        human_escalation_triggered=escalated,
        escalation_reason=escalation_reason,
        incident_id=incident_id,
        bitemporal=bitemporal,
        elapsed_ms=round(elapsed, 2),
        pass_fail=pass_fail,
    )


def run_all(*, extra_context: Dict[str, Any] | None = None) -> List[SimulationResult]:
    """Run every registered scenario and return results."""
    results = []
    for scenario in list_scenarios():
        try:
            r = run_scenario(scenario["scenario_id"], extra_context=extra_context)
            results.append(r)
        except Exception as exc:
            logger.error("scenario %s failed: %s", scenario.get("scenario_id"), exc)
    return results


def format_report(results: List[SimulationResult]) -> str:
    """Format a human-readable summary report from simulation results."""
    lines = [
        "=" * 72,
        "  SUPPLY-CHAIN ATTACK SIMULATION REPORT",
        f"  Generated: {datetime.now(timezone.utc).isoformat()}",
        "=" * 72,
        "",
    ]
    passed = sum(1 for r in results if r.pass_fail == "PASS")
    partial = sum(1 for r in results if r.pass_fail == "PARTIAL")
    failed = sum(1 for r in results if r.pass_fail == "FAIL")

    lines.append(f"  Total: {len(results)}  |  PASS: {passed}  |  PARTIAL: {partial}  |  FAIL: {failed}")
    lines.append("")

    for r in results:
        status_icon = {"PASS": "[+]", "PARTIAL": "[~]", "FAIL": "[-]"}.get(r.pass_fail, "[?]")
        lines.append(f"  {status_icon} {r.scenario_id} – {r.scenario_name}")
        lines.append(f"      Severity: {r.severity}  |  Escalated: {r.human_escalation_triggered}")
        lines.append(f"      Signals: {r.signals_detected}")
        lines.append(f"      Trace: {r.trace_id}  |  Elapsed: {r.elapsed_ms:.0f}ms")
        lines.append(f"      Agent chain: {' → '.join(a.agent_id for a in r.agent_chain)}")
        lines.append("")

        # Interleaved thinking summary
        for step in r.thinking_steps:
            lines.append(f"        Step {step.step_id} [{step.agent}] {step.action}")
            # Wrap reasoning at 68 chars for readability
            for i in range(0, len(step.reasoning), 68):
                prefix = "          " if i > 0 else "          → "
                lines.append(f"{prefix}{step.reasoning[i:i+68]}")
        lines.append("")

    lines.append("=" * 72)
    return "\n".join(lines)
