"""Bounded interleaving for Tier 2 thinking."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
import time
from src.app.services.registry import get_tool_allowlist_for_agent


class StopReason(Enum):
    MAX_ITERATIONS = "max_iterations"
    BUDGET_EXHAUSTED = "budget_exhausted"
    HIGH_CONFIDENCE = "high_confidence"
    USER_INTERRUPT = "user_interrupt"
    ERROR = "error"
    COMPLETE = "complete"
    TIMEOUT = "timeout"


@dataclass
class ToolCall:
    tool_name: str
    arguments: Dict[str, Any]
    result: Any
    latency_ms: float
    success: bool


@dataclass
class InterleavingState:
    """Track interleaving loop state."""
    iteration: int = 0
    tool_budget_remaining: int = 4
    confidence: float = 0.0
    tool_calls: List[ToolCall] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    stop_reason: Optional[StopReason] = None
    total_latency_ms: float = 0.0


@dataclass
class ThinkDecision:
    tool_name: Optional[str]
    arguments: Dict[str, Any] = field(default_factory=dict)
    stop: bool = False
    reason: Optional[str] = None
    confidence: Optional[float] = None


class InterleavingController:
    """Control bounded think→tool→observe loops."""

    # Tool allowlists per agent type
    TOOL_ALLOWLISTS = {
        "orchestrator": ["retrieve_context", "check_policy", "get_recommendations"],
        "fraud_scorer": ["check_phash", "verify_serial", "analyze_metadata", "check_history"],
        "inventory": ["check_stock", "query_supplier", "get_forecast", "check_demand"],
        "recommendations": ["search_products", "get_similar", "check_availability"],
        "cv": [
            "cv_analyze",
            "cv_tier_route",
            "cv_object_detect",
            "cv_damage_classify",
            "cv_ocr_extract",
            "cv_verify_serial",
            "cv_check_phash",
            "cv_reverse_image_search",
            "cv_image_forensics",
            "cv_ela_detect",
            "cv_splice_detect",
            "cv_quality_score",
            "cv_evidence_tags",
            "cv_hash_index",
            "cv_compare_claim",
            "cv_metadata_inspect",
            "cv_watermark_check",
            "cv_geo_tag_check",
            "cv_invoice_match",
            "cv_serial_match",
            "cv_damage_severity",
            "cv_blur_detect",
        ],
    }

    def __init__(
        self,
        agent_type: str,
        max_iterations: int = 3,
        tool_budget: int = 4,
        confidence_threshold: float = 0.9,
        timeout_ms: float = 5000,
        allowed_tools_override: Optional[List[str]] = None,
    ):
        self.agent_type = agent_type
        self.max_iterations = max_iterations
        self.tool_budget = tool_budget
        self.confidence_threshold = confidence_threshold
        self.timeout_ms = timeout_ms
        if allowed_tools_override is not None:
            self.allowed_tools = set(allowed_tools_override)
        else:
            static = set(self.TOOL_ALLOWLISTS.get(agent_type, []))
            dynamic = set(get_tool_allowlist_for_agent(agent_type))
            self.allowed_tools = static | dynamic

        self.state = InterleavingState(tool_budget_remaining=tool_budget)
        self.start_time = None

    def should_continue(self) -> bool:
        """Check if interleaving should continue."""
        if self.state.iteration >= self.max_iterations:
            self.state.stop_reason = StopReason.MAX_ITERATIONS
            return False
        if self.state.tool_budget_remaining <= 0:
            self.state.stop_reason = StopReason.BUDGET_EXHAUSTED
            return False
        if self.state.confidence >= self.confidence_threshold:
            self.state.stop_reason = StopReason.HIGH_CONFIDENCE
            return False
        if self.start_time and (time.time() - self.start_time) * 1000 > self.timeout_ms:
            self.state.stop_reason = StopReason.TIMEOUT
            return False
        return True

    def can_call_tool(self, tool_name: str) -> bool:
        if tool_name not in self.allowed_tools:
            return False
        if self.state.tool_budget_remaining <= 0:
            return False
        return True

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        latency_ms: float,
        success: bool = True,
    ):
        self.state.tool_calls.append(
            ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                latency_ms=latency_ms,
                success=success,
            )
        )
        self.state.tool_budget_remaining -= 1
        self.state.total_latency_ms += latency_ms

    def record_observation(self, observation: str):
        self.state.observations.append(observation)

    def update_confidence(self, new_confidence: float):
        self.state.confidence = max(self.state.confidence, new_confidence)

    def next_iteration(self):
        self.state.iteration += 1

    def start(self):
        self.start_time = time.time()

    def finish(self, reason: StopReason = StopReason.COMPLETE):
        if self.state.stop_reason is None:
            self.state.stop_reason = reason

    def get_summary(self) -> Dict[str, Any]:
        budget_exhausted = bool(self.state.stop_reason == StopReason.BUDGET_EXHAUSTED)
        return {
            "iterations": self.state.iteration,
            "tool_calls": len(self.state.tool_calls),
            "budget_used": self.tool_budget - self.state.tool_budget_remaining,
            "budget_remaining": self.state.tool_budget_remaining,
            "final_confidence": self.state.confidence,
            "stop_reason": self.state.stop_reason.value if self.state.stop_reason else None,
            "needs_human_review": budget_exhausted,
            "escalation_reason": "budget_exhausted" if budget_exhausted else None,
            "total_latency_ms": self.state.total_latency_ms,
            "observations": self.state.observations,
        }


def run_interleaved(
    controller: InterleavingController,
    think_fn: Callable[[InterleavingState], Optional[object]],  # Returns tool/args decision
    tool_fn: Callable[[str, Dict], Any],  # Executes tool
    observe_fn: Callable[[Any, InterleavingState], float],  # Returns raw confidence
    event_fn: Optional[Callable[[str, Dict[str, Any], InterleavingState], None]] = None,
    calibrate_fn: Optional[Callable[[float, InterleavingState], float]] = None,
    tool_policy_fn: Optional[Callable[[str, Dict[str, Any], InterleavingState], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Run a bounded interleaving loop.
    """
    controller.start()

    while controller.should_continue():
        controller.next_iteration()

        tool_to_call = None
        tool_args: Dict[str, Any] = {}
        think_raw = think_fn(controller.state)
        decision = _normalize_think_output(think_raw)

        if event_fn:
            try:
                event_fn(
                    "think",
                    {
                        "iteration": controller.state.iteration,
                        "tool_name": decision.tool_name,
                        "arguments": decision.arguments,
                        "stop": decision.stop,
                        "reason": decision.reason,
                        "confidence": decision.confidence,
                    },
                    controller.state,
                )
            except Exception:
                pass

        if decision.stop or decision.tool_name is None:
            controller.finish(StopReason.COMPLETE)
            break

        tool_to_call = decision.tool_name
        tool_args = decision.arguments or {}

        if not controller.can_call_tool(tool_to_call):
            reject_reason = "budget_exhausted" if controller.state.tool_budget_remaining <= 0 else "tool_not_allowed"
            controller.record_observation(f"Cannot call {tool_to_call}: {reject_reason}")
            if event_fn:
                try:
                    event_fn(
                        "tool_rejected",
                        {
                            "iteration": controller.state.iteration,
                            "tool_name": tool_to_call,
                            "reason": reject_reason,
                            "budget_remaining": controller.state.tool_budget_remaining,
                            "allowed_tools": sorted(list(controller.allowed_tools)),
                        },
                        controller.state,
                    )
                except Exception:
                    pass
            continue

        if tool_policy_fn:
            try:
                gate = tool_policy_fn(tool_to_call, tool_args, controller.state) or {}
            except Exception:
                gate = {"allow": False, "reason": "policy_error", "action": "security_review"}
            allow = bool(gate.get("allow", False))
            if not allow:
                reject_reason = str(gate.get("reason") or "policy_denied")
                controller.record_observation(f"Cannot call {tool_to_call}: {reject_reason}")
                if event_fn:
                    try:
                        event_fn(
                            "tool_rejected",
                            {
                                "iteration": controller.state.iteration,
                                "tool_name": tool_to_call,
                                "reason": "policy_denied",
                                "policy_reason": reject_reason,
                                "policy_action": gate.get("action"),
                                "policy_rule_hits": gate.get("rule_hits") or {},
                                "budget_remaining": controller.state.tool_budget_remaining,
                            },
                            controller.state,
                        )
                    except Exception:
                        pass
                continue

        start = time.time()
        try:
            result = tool_fn(tool_to_call, tool_args)
            latency = (time.time() - start) * 1000
            controller.record_tool_call(tool_to_call, tool_args, result, latency, success=True)
        except Exception as e:
            latency = (time.time() - start) * 1000
            controller.record_tool_call(tool_to_call, tool_args, str(e), latency, success=False)
            controller.record_observation(f"Tool {tool_to_call} failed: {e}")
            if event_fn:
                try:
                    event_fn(
                        "tool_error",
                        {"iteration": controller.state.iteration, "tool_name": tool_to_call, "error": str(e)},
                        controller.state,
                    )
                except Exception:
                    pass
            continue
        if event_fn:
            try:
                event_fn(
                    "tool_result",
                    {
                        "iteration": controller.state.iteration,
                        "tool_name": tool_to_call,
                        "arguments": tool_args,
                        "latency_ms": latency,
                        "success": True,
                    },
                    controller.state,
                )
            except Exception:
                pass

        raw_confidence = observe_fn(result, controller.state)
        calibrated = raw_confidence
        if calibrate_fn:
            try:
                calibrated = calibrate_fn(raw_confidence, controller.state)
            except Exception:
                calibrated = raw_confidence
        controller.update_confidence(calibrated)
        controller.record_observation(
            f"After {tool_to_call}: raw_confidence={raw_confidence:.2f}, calibrated_confidence={calibrated:.2f}"
        )
        if event_fn:
            try:
                event_fn(
                    "observe",
                    {
                        "iteration": controller.state.iteration,
                        "tool_name": tool_to_call,
                        "raw_confidence": raw_confidence,
                        "calibrated_confidence": calibrated,
                    },
                    controller.state,
                )
            except Exception:
                pass

    if event_fn:
        try:
            event_fn(
                "stop",
                {
                    "iteration": controller.state.iteration,
                    "stop_reason": controller.state.stop_reason.value if controller.state.stop_reason else None,
                    "final_confidence": controller.state.confidence,
                },
                controller.state,
            )
        except Exception:
            pass
    return controller.get_summary()


def _normalize_think_output(value: Optional[object]) -> ThinkDecision:
    if value is None:
        return ThinkDecision(tool_name=None, stop=True, reason="no_tool")
    if isinstance(value, ThinkDecision):
        return value
    if isinstance(value, str):
        return ThinkDecision(tool_name=value)
    if isinstance(value, dict):
        tool_name = value.get("tool") or value.get("tool_name") or value.get("next_tool")
        stop = bool(value.get("stop")) if "stop" in value else False
        args = value.get("arguments") or value.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        return ThinkDecision(
            tool_name=tool_name,
            arguments=args,
            stop=stop,
            reason=value.get("reason"),
            confidence=value.get("confidence") if isinstance(value.get("confidence"), (int, float)) else None,
        )
    return ThinkDecision(tool_name=None, stop=True, reason="invalid_think_output")
