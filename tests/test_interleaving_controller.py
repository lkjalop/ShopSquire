from src.app.services.interleaving_controller import InterleavingController, run_interleaved


def test_interleaving_passes_tool_args():
    controller = InterleavingController(agent_type="orchestrator", max_iterations=1, tool_budget=1)
    seen = {}

    def think_fn(_state):
        return {"tool_name": "retrieve_context", "arguments": {"force": True}}

    def tool_fn(name, args):
        seen["name"] = name
        seen["args"] = args
        return {"ok": True}

    def observe_fn(_result, _state):
        return 0.4

    summary = run_interleaved(controller, think_fn, tool_fn, observe_fn)
    assert summary["tool_calls"] == 1
    assert seen["name"] == "retrieve_context"
    assert seen["args"] == {"force": True}


def test_interleaving_calibration_affects_confidence():
    controller = InterleavingController(agent_type="orchestrator", max_iterations=1, tool_budget=1, confidence_threshold=0.75)

    def think_fn(_state):
        return "check_policy"

    def tool_fn(_name, _args):
        return {"policy": {"allowed": True, "approval_required": False}}

    def observe_fn(_result, _state):
        return 0.4

    def calibrate_fn(raw, _state):
        return 0.85 if raw < 0.5 else raw

    summary = run_interleaved(controller, think_fn, tool_fn, observe_fn, calibrate_fn=calibrate_fn)
    assert summary["final_confidence"] >= 0.85
    assert summary["stop_reason"] in ("high_confidence", "max_iterations")


def test_interleaving_emits_events():
    controller = InterleavingController(agent_type="orchestrator", max_iterations=1, tool_budget=1)
    events = []

    def think_fn(_state):
        return "retrieve_context"

    def tool_fn(_name, _args):
        return {"ok": True}

    def observe_fn(_result, _state):
        return 0.2

    def event_fn(event_type, payload, _state):
        events.append((event_type, payload))

    run_interleaved(controller, think_fn, tool_fn, observe_fn, event_fn=event_fn)
    event_types = [e[0] for e in events]
    assert "think" in event_types
    assert "tool_result" in event_types
    assert "observe" in event_types
    assert "stop" in event_types


def test_interleaving_execution_policy_gate_denies_tool():
    controller = InterleavingController(agent_type="orchestrator", max_iterations=1, tool_budget=1)
    events = []
    called = {"count": 0}

    def think_fn(_state):
        return {"tool_name": "retrieve_context", "arguments": {"force": True}}

    def tool_fn(_name, _args):
        called["count"] += 1
        return {"ok": True}

    def observe_fn(_result, _state):
        return 0.2

    def event_fn(event_type, payload, _state):
        events.append((event_type, payload))

    def tool_policy_fn(_tool_name, _args, _state):
        return {"allow": False, "reason": "security_observer_high_risk", "action": "security_review", "rule_hits": {"observer": 1.0}}

    summary = run_interleaved(
        controller,
        think_fn,
        tool_fn,
        observe_fn,
        event_fn=event_fn,
        tool_policy_fn=tool_policy_fn,
    )
    assert called["count"] == 0
    assert summary["tool_calls"] == 0
    rejected = [e for e in events if e[0] == "tool_rejected"]
    assert rejected
    assert rejected[0][1].get("reason") == "policy_denied"
    assert rejected[0][1].get("policy_reason") == "security_observer_high_risk"
