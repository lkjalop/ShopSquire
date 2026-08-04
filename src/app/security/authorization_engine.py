"""Authorization Engine — the deterministic Tier-1 control-plane gate.

AI proposes; this engine disposes. Every privileged action (refund, return,
order-modification, reshipment, supplier-order, fraud-disposition) is meant to
pass through ``authorize_action()`` *before* it executes. The engine is a
unification of three patterns the codebase already ships — it is not a new
subsystem, it is the generalisation of what the grounding ladder does for one
narrow case (product identity) into the one gate the autonomy decks call the
single most important control:

  * ``image_feature_gate.FeatureAllowlist`` — a verdict + reason + an auditable
    ``to_dict()`` that lands in the decision trace.
  * ``maestro_boundaries``                  — per-agent lanes, autonomous value
    caps, and an audit/warn/block enforcement mode driven by an env var.
  * ``grounding_ladder``                    — *assert-to-evidence,
    escalate-the-residual*; a pure, unit-testable core behind a thin I/O shell.

Design answers (see docs/SHOPSQUIRE_AUTONOMY_COMPLIANCE_GAP_2026-06-14.md):

  Less brittle      Policy is externalised + versioned (config/authorization_policy.json).
                    Tuning a threshold/cap needs no code change. ANY error inside the
                    engine fails CLOSED to deny + safe_pause. Idempotency keys make a
                    replayed request return the prior verdict instead of re-deciding —
                    no double refunds.
  Lane-keeping      Each action declares ``allowed_requesters``. An agent asking for an
                    action outside its lane is not merely denied — ``out_of_lane`` is a
                    COMPROMISE signal, because a well-behaved agent never asks.
  Compromise detect prompt-injection / jailbreak / tool-poisoning / memory-manipulation /
                    out-of-lane / contradicted-evidence each trip a guardrail →
                    safe_pause (or quarantine for fraud) + a security event.
  Shadow mode       ``default_mode = "shadow"`` evaluates and logs the decision but does
                    NOT enforce it, so turning the engine on cannot break the platform.
                    Flip an action (or everything) to ``active`` once its callers honour
                    the verdict; ``AUTHZ_ENGINE_MODE=off`` is the global kill switch.
  UI / UX           Every call emits an ``authorization_decision`` trace event (renders in
                    the Decision Trace popup) carrying the *residual* — the plain-English
                    "what would flip deny → allow".

Maps to: OWASP Agentic AI AA01 (Agent Authorization & Control Hijacking), AA03
(Trust Boundary Violations); MAESTRO bounded autonomy; EU AI Act Art. 14 (human
oversight) + Art. 9 (risk management); ISO 42001 AI governance; NIST AI RMF
GOVERN/MANAGE.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

_log = logging.getLogger("shopsquire.authorization_engine")


def _authz_log_failure(stage: str, exc: BaseException | None = None) -> None:
    """Make an otherwise-silent control-plane side-effect failure observable.

    Side effects (trace emit, control-plane writes, security event) are
    best-effort by design — they must never affect the verdict — but
    "best-effort" must not mean "invisible". Every swallowed failure is logged
    at debug and counted on a Prometheus metric so a broken sink shows up.
    """
    try:
        _log.debug("authorization_engine side-effect failed at %s: %r", stage, exc)
    except Exception:
        pass
    try:
        from src.app.observability.metrics import record_authz_write_failure
        record_authz_write_failure(stage)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Decision + mode vocabulary
# ---------------------------------------------------------------------------
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_ESCALATE = "escalate"

MODE_SHADOW = "shadow"   # evaluate + log, do NOT enforce (safe default for rollout)
MODE_ACTIVE = "active"   # evaluate + log + enforce (caller MUST honour the verdict)
MODE_OFF = "off"         # global kill switch — pass everything through unevaluated
_VALID_MODES: FrozenSet[str] = frozenset({MODE_SHADOW, MODE_ACTIVE, MODE_OFF})

# Signals that mean the *request itself* is untrustworthy. These are not business
# preconditions (those live in the policy's ``prohibited_when``) — they indicate the
# agent or its inputs may be compromised, so they short-circuit to a safe halt and
# raise a real security event rather than a polite policy rejection.
_COMPROMISE_SIGNALS: FrozenSet[str] = frozenset({
    "prompt_injection_detected",
    "jailbreak_detected",
    "tool_poisoning_detected",
    "memory_manipulation_detected",
    "rag_exfiltration_detected",
    "claim_contradicted",     # evidence directly contradicts what's being requested
    # ``out_of_lane`` is added by the engine, not the caller (see authorize()).
})

_FALLBACK_TERMINAL = "safe_pause"  # the universal fail-closed outcome


# ---------------------------------------------------------------------------
# Request / decision dataclasses
# ---------------------------------------------------------------------------
@dataclass
class AuthorizationContext:
    """One privileged-action request presented to the gate."""
    action: str
    requester: str                                   # the agent asking (MAESTRO agent name)
    value_usd: float = 0.0
    confidence: float = 1.0                           # caller's confidence the action is correct
    conditions: FrozenSet[str] = frozenset()          # observed business state, matched vs prohibited_when
    signals: FrozenSet[str] = frozenset()             # observed security signals (compromise candidates)
    idempotency_key: Optional[str] = None
    subject_id: Optional[str] = None                  # order / customer / supplier id (for audit)
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Lane-keeping applies to AUTONOMOUS AGENTS. Human-authenticated callers (the
    # route_enforcement seam, where FastAPI deps already established identity) set
    # this False — there is no agent lane to police there.
    enforce_lane: bool = True


@dataclass
class AuthorizationDecision:
    """The disposed outcome. ``to_dict()`` is what lands in the decision trace."""
    decision: str                      # allow | deny | escalate
    terminal_outcome: str              # one of policy["terminal_outcomes"]
    action: str
    requester: str
    reason: str
    policy_version: str
    mode: str = MODE_SHADOW
    enforced: bool = False             # active mode → the caller must honour this
    residual: Optional[str] = None     # plain-English "what would flip deny → allow"
    guardrails_tripped: List[str] = field(default_factory=list)
    compromise_signals: List[str] = field(default_factory=list)
    value_usd: float = 0.0
    confidence: float = 1.0
    idempotency_key: Optional[str] = None
    cached: bool = False               # served from the idempotency cache (replay)

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW

    def should_block(self) -> bool:
        """True when the caller MUST NOT proceed.

        In shadow mode this is always False (advisory only) so the engine cannot
        break existing behaviour; the would-be verdict is still logged + traced.
        """
        return self.enforced and self.decision != DECISION_ALLOW

    @property
    def is_compromise(self) -> bool:
        return bool(self.compromise_signals)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "terminal_outcome": self.terminal_outcome,
            "action": self.action,
            "requester": self.requester,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "mode": self.mode,
            "enforced": self.enforced,
            "should_block": self.should_block(),
            "residual": self.residual,
            "guardrails_tripped": list(self.guardrails_tripped),
            "compromise_signals": list(self.compromise_signals),
            "value_usd": round(float(self.value_usd), 2),
            "confidence": round(float(self.confidence), 3),
            "idempotency_key": self.idempotency_key,
            "cached": self.cached,
        }


# ---------------------------------------------------------------------------
# Policy loader — externalised + hot-reloaded on file mtime (no restart to tune)
# ---------------------------------------------------------------------------
_POLICY_CACHE: Dict[str, Any] = {"data": None, "mtime": 0.0, "path": None}
_POLICY_LOCK = threading.Lock()


def _policy_path() -> str:
    env = os.getenv("AUTHZ_POLICY_PATH")
    if env:
        return env
    # src/app/security/authorization_engine.py -> parents[3] == repo root
    return str(Path(__file__).resolve().parents[3] / "config" / "authorization_policy.json")


def load_policy(force: bool = False) -> Dict[str, Any]:
    """Return the parsed policy, reloading only when the file changes on disk.

    Raises on a missing/invalid file so the caller can fail closed — a gate with
    no policy must deny, never silently allow.
    """
    path = _policy_path()
    with _POLICY_LOCK:
        try:
            mtime = os.path.getmtime(path)
        except OSError as exc:
            raise FileNotFoundError(f"authorization policy not found at {path}") from exc
        cached = _POLICY_CACHE.get("data")
        if (
            not force
            and cached is not None
            and _POLICY_CACHE.get("path") == path
            and float(_POLICY_CACHE.get("mtime") or 0.0) == mtime
        ):
            return cached
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("actions"), dict):
            raise ValueError("authorization policy malformed: missing 'actions' object")
        _POLICY_CACHE.update({"data": data, "mtime": mtime, "path": path})
        return data


# ---------------------------------------------------------------------------
# Pure decision core — deterministic, fully unit-testable, no I/O.
# ---------------------------------------------------------------------------
def authorize(ctx: AuthorizationContext, policy: Dict[str, Any]) -> AuthorizationDecision:
    """The deterministic gate. Given a request + policy, return a verdict.

    Pipeline (each step can short-circuit to a terminal outcome):
      0. unknown action            → fail closed (safe_pause, compromise: unknown_action)
      1. lane check                → out-of-lane is a compromise signal
      2. compromise signals        → safe_pause / quarantine + security event
      3. prohibited preconditions  → policy default terminal (e.g. reject_under_policy)
      4. confidence floor          → policy default terminal (often request_customer_evidence)
      5. value bands               → governance escalation or hard safe_pause
      6. all clear                 → execute
    """
    version = str(policy.get("version") or "unknown")
    action_policy = (policy.get("actions") or {}).get(ctx.action)

    # 0. Unknown action — the gate has no mandate for it, so it cannot allow it.
    if not isinstance(action_policy, dict):
        return AuthorizationDecision(
            decision=DECISION_DENY,
            terminal_outcome=_FALLBACK_TERMINAL,
            action=ctx.action,
            requester=ctx.requester,
            reason=f"unknown_action:{ctx.action}",
            policy_version=version,
            guardrails_tripped=["unknown_action"],
            compromise_signals=["unknown_action"],
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )

    # 1. Lane check. A registered agent that asks for an action outside its lane is
    #    not just unauthorised — that request is itself anomalous, so it is treated
    #    as a compromise signal, not a polite denial. Only enforced for autonomous
    #    agents (ctx.enforce_lane) on actions that actually DECLARE a lane; the
    #    human-authenticated seam has no agent lane to police.
    allowed_requesters = {str(r) for r in (action_policy.get("allowed_requesters") or [])}
    out_of_lane = (
        ctx.enforce_lane
        and bool(allowed_requesters)
        and bool(ctx.requester)
        and ctx.requester not in allowed_requesters
    )

    # 2. Compromise signals (caller-supplied + engine-derived) → safe halt.
    compromise = set(s for s in ctx.signals if s in _COMPROMISE_SIGNALS)
    if out_of_lane:
        compromise.add("out_of_lane")
    if compromise:
        # fraud dispositions quarantine the subject; everything else pauses safely.
        terminal = "quarantine" if ctx.action == "fraud_disposition" else _FALLBACK_TERMINAL
        residual = (
            "Re-issue the request from an authorised agent."
            if "out_of_lane" in compromise
            else "Clear the security signal (re-verify inputs / re-authenticate the session)."
        )
        return AuthorizationDecision(
            decision=DECISION_DENY,
            terminal_outcome=terminal,
            action=ctx.action,
            requester=ctx.requester,
            reason="compromise_signal:" + ",".join(sorted(compromise)),
            policy_version=version,
            residual=residual,
            guardrails_tripped=sorted(compromise),
            compromise_signals=sorted(compromise),
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )

    default_terminal = str(action_policy.get("default_terminal") or "reject_under_policy")

    # 2b. Hard block — this action can NEVER be autonomously authorised (bank-detail
    #     changes, bulk PII export, egress to unlisted domains). Maps to the legacy
    #     authority-matrix BLOCK. Unconditional, value-independent.
    if action_policy.get("hard_block"):
        return AuthorizationDecision(
            decision=DECISION_DENY,
            terminal_outcome="reject_under_policy",
            action=ctx.action,
            requester=ctx.requester,
            reason="hard_block",
            policy_version=version,
            residual="This action cannot be autonomously authorised; use the approved out-of-band workflow.",
            guardrails_tripped=["hard_block"],
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )

    # 3. Prohibited preconditions — observed business state the action forbids.
    prohibited = {str(p) for p in (action_policy.get("prohibited_when") or [])}
    hit = prohibited & {str(c) for c in ctx.conditions}
    if hit:
        return AuthorizationDecision(
            decision=DECISION_DENY,
            terminal_outcome=default_terminal,
            action=ctx.action,
            requester=ctx.requester,
            reason="prohibited_precondition:" + ",".join(sorted(hit)),
            policy_version=version,
            residual=f"Resolve precondition(s): {', '.join(sorted(hit))}.",
            guardrails_tripped=["prohibited_precondition"],
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )

    # 4. Confidence floor.
    min_conf = float(action_policy.get("min_confidence") or 0.0)
    if ctx.confidence < min_conf:
        return AuthorizationDecision(
            decision=DECISION_DENY,
            terminal_outcome=default_terminal,
            action=ctx.action,
            requester=ctx.requester,
            reason=f"confidence_below_floor:{ctx.confidence:.3f}<{min_conf:.3f}",
            policy_version=version,
            residual=f"Raise decision confidence to ≥ {min_conf:.2f} (gather more evidence).",
            guardrails_tripped=["confidence_floor"],
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )

    # 4b. Never-auto — legitimate but never autonomously executable (new-supplier
    #     onboarding, account recovery). Always routes to governance regardless of
    #     value. Maps to the legacy authority-matrix HUMAN_REVIEW/DUAL_CONTROL, but
    #     to a GOVERNANCE boundary, not a runtime employee gate.
    if action_policy.get("never_auto"):
        return AuthorizationDecision(
            decision=DECISION_ESCALATE,
            terminal_outcome="escalate_governance",
            action=ctx.action,
            requester=ctx.requester,
            reason="never_auto",
            policy_version=version,
            residual="This action always requires governance approval before it can proceed.",
            guardrails_tripped=["never_auto"],
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )

    # 5. Value bands.
    #    value ≤ value_cap                     → may auto-execute
    #    value_cap < value ≤ governance_cap    → escalate to governance (NOT a runtime
    #                                            employee gate — a governance boundary)
    #    value > governance_cap                → hard safe_pause
    value_cap = float(action_policy.get("value_cap_usd") or 0.0)
    gov_cap = float(action_policy.get("governance_cap_usd") or value_cap)
    if ctx.value_usd > gov_cap:
        return AuthorizationDecision(
            decision=DECISION_DENY,
            terminal_outcome=_FALLBACK_TERMINAL,
            action=ctx.action,
            requester=ctx.requester,
            reason=f"value_over_governance_cap:{ctx.value_usd:.2f}>{gov_cap:.2f}",
            policy_version=version,
            residual=f"Amount exceeds the governance ceiling (${gov_cap:.0f}); split or route via governance.",
            guardrails_tripped=["governance_cap"],
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )
    if ctx.value_usd > value_cap:
        return AuthorizationDecision(
            decision=DECISION_ESCALATE,
            terminal_outcome="escalate_governance",
            action=ctx.action,
            requester=ctx.requester,
            reason=f"value_over_auto_cap:{ctx.value_usd:.2f}>{value_cap:.2f}",
            policy_version=version,
            residual=f"Within governance band (≤ ${gov_cap:.0f}); needs governance approval to proceed.",
            guardrails_tripped=["value_cap"],
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )

    # 6. All clear.
    return AuthorizationDecision(
        decision=DECISION_ALLOW,
        terminal_outcome="execute",
        action=ctx.action,
        requester=ctx.requester,
        reason="all_checks_passed",
        policy_version=version,
        value_usd=ctx.value_usd,
        confidence=ctx.confidence,
        idempotency_key=ctx.idempotency_key,
    )


# ---------------------------------------------------------------------------
# Mode resolution — kill switch > per-action override > env > policy default.
# ---------------------------------------------------------------------------
def _resolve_mode(action: str, policy: Dict[str, Any]) -> str:
    env = os.getenv("AUTHZ_ENGINE_MODE", "").strip().lower()
    if env == MODE_OFF:
        return MODE_OFF  # emergency kill switch always wins
    action_policy = (policy.get("actions") or {}).get(action) or {}
    per_action = str(action_policy.get("mode") or "").strip().lower()
    if per_action in _VALID_MODES:
        return per_action
    if env in _VALID_MODES:
        return env
    base = str(policy.get("default_mode") or MODE_SHADOW).strip().lower()
    return base if base in _VALID_MODES else MODE_SHADOW


# ---------------------------------------------------------------------------
# Idempotency cache — a replayed key returns the prior verdict (no double-exec).
# ---------------------------------------------------------------------------
_IDEMPOTENCY_CACHE: "Dict[str, tuple[float, Dict[str, Any]]]" = {}
_IDEMPOTENCY_LOCK = threading.Lock()
_IDEMPOTENCY_TTL_SECONDS = int(os.getenv("AUTHZ_IDEMPOTENCY_TTL", "86400") or 86400)
_IDEMPOTENCY_MAX = 4096


def _idem_get(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _IDEMPOTENCY_LOCK:
        entry = _IDEMPOTENCY_CACHE.get(key)
        if not entry:
            return None
        ts, payload = entry
        if now - ts > _IDEMPOTENCY_TTL_SECONDS:
            _IDEMPOTENCY_CACHE.pop(key, None)
            return None
        return payload


def _idem_put(key: str, payload: Dict[str, Any]) -> None:
    with _IDEMPOTENCY_LOCK:
        if len(_IDEMPOTENCY_CACHE) >= _IDEMPOTENCY_MAX:
            # drop the oldest ~10% to bound memory
            for k in sorted(_IDEMPOTENCY_CACHE, key=lambda k: _IDEMPOTENCY_CACHE[k][0])[: _IDEMPOTENCY_MAX // 10]:
                _IDEMPOTENCY_CACHE.pop(k, None)
        _IDEMPOTENCY_CACHE[key] = (time.time(), payload)


# ---------------------------------------------------------------------------
# I/O orchestrator — the public entry point. Loads policy, decides, applies mode,
# logs to the control plane (best-effort), and emits the trace event.
# ---------------------------------------------------------------------------
def authorize_action(
    action: str,
    requester: str,
    *,
    value_usd: float = 0.0,
    confidence: float = 1.0,
    conditions: Optional[Any] = None,
    signals: Optional[Any] = None,
    idempotency_key: Optional[str] = None,
    subject_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    enforce_lane: bool = True,
) -> AuthorizationDecision:
    """Authorize a privileged action. Always returns a decision; never raises.

    Callers gate execution on ``decision.should_block()`` (True only in active
    mode). In shadow mode the verdict is advisory but still fully logged + traced,
    which is what lets the engine be rolled out without risk.

    ``enforce_lane=False`` for human-authenticated callers (the route_enforcement
    seam) where there is no autonomous-agent lane to police.
    """
    ctx = AuthorizationContext(
        action=str(action),
        requester=str(requester),
        value_usd=float(value_usd or 0.0),
        confidence=float(confidence if confidence is not None else 1.0),
        conditions=frozenset(str(c) for c in (conditions or [])),
        signals=frozenset(str(s) for s in (signals or [])),
        idempotency_key=idempotency_key,
        subject_id=subject_id,
        trace_id=trace_id,
        metadata=dict(metadata or {}),
        enforce_lane=enforce_lane,
    )

    # Load policy first — a failure here MUST fail closed.
    try:
        policy = load_policy()
    except Exception as exc:  # missing / malformed policy
        decision = _fail_closed(ctx, reason=f"policy_load_error:{type(exc).__name__}")
        _emit_and_log(decision, ctx)
        return decision

    mode = _resolve_mode(ctx.action, policy)

    # Global kill switch: pass through unevaluated (but still emit a trace breadcrumb).
    if mode == MODE_OFF:
        decision = AuthorizationDecision(
            decision=DECISION_ALLOW,
            terminal_outcome="execute",
            action=ctx.action,
            requester=ctx.requester,
            reason="engine_off",
            policy_version=str(policy.get("version") or "unknown"),
            mode=MODE_OFF,
            enforced=False,
            value_usd=ctx.value_usd,
            confidence=ctx.confidence,
            idempotency_key=ctx.idempotency_key,
        )
        _emit_and_log(decision, ctx)
        return decision

    # Idempotency replay: same key → prior verdict, no re-decision.
    if ctx.idempotency_key:
        prior = _idem_get(ctx.idempotency_key)
        if prior is not None:
            replayed = _decision_from_dict(prior)
            replayed.cached = True
            _emit_and_log(replayed, ctx)
            return replayed

    # Decide (fail closed on any unexpected error in the pure core).
    try:
        decision = authorize(ctx, policy)
    except Exception as exc:
        decision = _fail_closed(ctx, reason=f"engine_error:{type(exc).__name__}", version=str(policy.get("version") or "unknown"))

    decision.mode = mode
    decision.enforced = (mode == MODE_ACTIVE)

    if ctx.idempotency_key:
        _idem_put(ctx.idempotency_key, decision.to_dict())

    _emit_and_log(decision, ctx)
    _record_decision_metric(decision)
    return decision


def _record_decision_metric(decision: AuthorizationDecision) -> None:
    try:
        from src.app.observability.metrics import record_authz_decision
        record_authz_decision(decision.action, decision.decision, decision.mode)
    except Exception as exc:
        _authz_log_failure("decision_metric", exc)


def _fail_closed(ctx: AuthorizationContext, *, reason: str, version: str = "unavailable") -> AuthorizationDecision:
    """The universal safe verdict when the engine cannot reason: deny + safe_pause.

    Note: enforced=True so a fail-closed verdict halts even mid-rollout — a gate
    that cannot evaluate must not silently allow privileged actions.
    """
    return AuthorizationDecision(
        decision=DECISION_DENY,
        terminal_outcome=_FALLBACK_TERMINAL,
        action=ctx.action,
        requester=ctx.requester,
        reason=reason,
        policy_version=version,
        mode=MODE_ACTIVE,
        enforced=True,
        residual="Engine could not evaluate; resolve the engine/policy fault then retry.",
        guardrails_tripped=["fail_closed"],
        value_usd=ctx.value_usd,
        confidence=ctx.confidence,
        idempotency_key=ctx.idempotency_key,
    )


def _decision_from_dict(d: Dict[str, Any]) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=str(d.get("decision") or DECISION_DENY),
        terminal_outcome=str(d.get("terminal_outcome") or _FALLBACK_TERMINAL),
        action=str(d.get("action") or ""),
        requester=str(d.get("requester") or ""),
        reason=str(d.get("reason") or ""),
        policy_version=str(d.get("policy_version") or "unknown"),
        mode=str(d.get("mode") or MODE_SHADOW),
        enforced=bool(d.get("enforced")),
        residual=d.get("residual"),
        guardrails_tripped=list(d.get("guardrails_tripped") or []),
        compromise_signals=list(d.get("compromise_signals") or []),
        value_usd=float(d.get("value_usd") or 0.0),
        confidence=float(d.get("confidence") or 0.0),
        idempotency_key=d.get("idempotency_key"),
    )


# ---------------------------------------------------------------------------
# Side effects — trace event for the UI + best-effort control-plane logging.
# Everything here is wrapped so a logging failure can never affect the verdict.
# ---------------------------------------------------------------------------
def _emit_and_log(decision: AuthorizationDecision, ctx: AuthorizationContext) -> None:
    _emit_trace_event(decision, ctx)
    _log_policy_evaluation(decision, ctx)
    _log_ai_interaction(decision, ctx)
    if ctx.idempotency_key:
        _track_retry(decision, ctx)
    # A cached replay must NOT open a second exception for the same logical
    # failure — the original call already enqueued it (idempotency means one
    # outcome, one exception row).
    if decision.decision != DECISION_ALLOW and not decision.cached:
        _enqueue_exception(decision, ctx)
    if decision.is_compromise:
        _raise_security_event(decision, ctx)


def _emit_trace_event(decision: AuthorizationDecision, ctx: AuthorizationContext) -> None:
    """Surface the decision in the Decision Trace popup (best-effort)."""
    if not ctx.trace_id:
        return
    try:
        from src.app.services.decision_log import log_trace_event
        payload = decision.to_dict()
        if ctx.subject_id:
            payload["subject_id"] = ctx.subject_id
        if ctx.idempotency_key:
            payload["idempotency_key"] = ctx.idempotency_key  # also dedups the trace row
        log_trace_event(
            trace_id=ctx.trace_id,
            event_type="authorization_decision",
            source_type="authorization_engine",
            source_id="authorization_engine",
            target_type="action",
            target_id=ctx.action,
            payload=payload,
        )
    except Exception as exc:
        _authz_log_failure("trace_event", exc)


def _control_plane_enabled() -> bool:
    # On by default; set AUTHZ_CONTROL_PLANE_LOG=0 to disable (e.g. before the
    # migration has run). Writes are best-effort regardless.
    return str(os.getenv("AUTHZ_CONTROL_PLANE_LOG", "1")).strip().lower() in ("1", "true", "yes", "on")


def _cp_insert(sql: str, params: Dict[str, Any], stage: str) -> None:
    """Best-effort control-plane write: own session, own commit, OBSERVABLE failure.

    One helper for all four control-plane tables so the session/commit/error
    handling lives in exactly one place. Each write keeps its own session (these
    are low-frequency privileged actions) so one failing sink never loses the
    others. A failure here is logged + counted — never silently swallowed.
    """
    if not _control_plane_enabled():
        return
    try:
        from sqlalchemy import text
        from src.app.models.db import db_session
        with db_session() as db:
            db.execute(text(sql), params)
            try:
                db.commit()
            except Exception as exc:
                _authz_log_failure(stage + "_commit", exc)
    except Exception as exc:
        _authz_log_failure(stage, exc)


def _log_policy_evaluation(decision: AuthorizationDecision, ctx: AuthorizationContext) -> None:
    _cp_insert(
        """
        INSERT INTO policy_evaluation_log (
            id, trace_id, policy_version, action, requester, decision,
            terminal_outcome, mode, enforced, reason, value_usd, confidence,
            guardrails_json, compromise_json, residual, created_at
        ) VALUES (
            :id, :trace_id, :policy_version, :action, :requester, :decision,
            :terminal_outcome, :mode, :enforced, :reason, :value_usd, :confidence,
            :guardrails_json, :compromise_json, :residual, :created_at
        )
        """,
        {
            "id": str(uuid.uuid4()),
            "trace_id": ctx.trace_id,
            "policy_version": decision.policy_version,
            "action": decision.action,
            "requester": decision.requester,
            "decision": decision.decision,
            "terminal_outcome": decision.terminal_outcome,
            "mode": decision.mode,
            "enforced": 1 if decision.enforced else 0,
            "reason": decision.reason,
            "value_usd": float(decision.value_usd),
            "confidence": float(decision.confidence),
            "guardrails_json": json.dumps(decision.guardrails_tripped),
            "compromise_json": json.dumps(decision.compromise_signals),
            "residual": decision.residual,
            "created_at": _now_iso(),
        },
        "policy_evaluation_log",
    )


def _log_ai_interaction(decision: AuthorizationDecision, ctx: AuthorizationContext) -> None:
    proposed = {
        "action": ctx.action,
        "requester": ctx.requester,
        "value_usd": ctx.value_usd,
        "confidence": ctx.confidence,
        "conditions": sorted(ctx.conditions),
        "signals": sorted(ctx.signals),
    }
    _cp_insert(
        """
        INSERT INTO ai_interaction_log (
            id, trace_id, interaction_type, actor, action,
            proposed_json, disposed_json, subject_id, created_at
        ) VALUES (
            :id, :trace_id, :interaction_type, :actor, :action,
            :proposed_json, :disposed_json, :subject_id, :created_at
        )
        """,
        {
            "id": str(uuid.uuid4()),
            "trace_id": ctx.trace_id,
            "interaction_type": "authorization",
            "actor": ctx.requester,
            "action": ctx.action,
            "proposed_json": json.dumps(proposed),
            "disposed_json": json.dumps(decision.to_dict()),
            "subject_id": ctx.subject_id,
            "created_at": _now_iso(),
        },
        "ai_interaction_log",
    )


def _track_retry(decision: AuthorizationDecision, ctx: AuthorizationContext) -> None:
    """Populate retry_tracking, keyed by idempotency_key; bump attempt_count on replay.

    Upsert is portable across SQLite + Postgres (``excluded`` row, unqualified
    existing-row columns)."""
    if not ctx.idempotency_key:
        return
    now = _now_iso()
    _cp_insert(
        """
        INSERT INTO retry_tracking (
            idempotency_key, action, requester, decision, terminal_outcome,
            attempt_count, last_status, first_seen_at, last_attempt_at
        ) VALUES (
            :idempotency_key, :action, :requester, :decision, :terminal_outcome,
            1, :last_status, :now, :now
        )
        ON CONFLICT (idempotency_key) DO UPDATE SET
            attempt_count = attempt_count + 1,
            last_status = excluded.last_status,
            last_attempt_at = excluded.last_attempt_at,
            decision = excluded.decision,
            terminal_outcome = excluded.terminal_outcome
        """,
        {
            "idempotency_key": ctx.idempotency_key,
            "action": decision.action,
            "requester": decision.requester,
            "decision": decision.decision,
            "terminal_outcome": decision.terminal_outcome,
            "last_status": "replayed" if decision.cached else "evaluated",
            "now": now,
        },
        "retry_tracking",
    )


def _enqueue_exception(decision: AuthorizationDecision, ctx: AuthorizationContext) -> None:
    """Guarantee every non-execute outcome has a tracked, terminal resolution path."""
    _cp_insert(
        """
        INSERT INTO exception_queue (
            id, trace_id, action, requester, terminal_outcome, reason,
            subject_id, value_usd, residual, status, created_at
        ) VALUES (
            :id, :trace_id, :action, :requester, :terminal_outcome, :reason,
            :subject_id, :value_usd, :residual, 'open', :created_at
        )
        """,
        {
            "id": str(uuid.uuid4()),
            "trace_id": ctx.trace_id,
            "action": decision.action,
            "requester": decision.requester,
            "terminal_outcome": decision.terminal_outcome,
            "reason": decision.reason,
            "subject_id": ctx.subject_id,
            "value_usd": float(decision.value_usd),
            "residual": decision.residual,
            "created_at": _now_iso(),
        },
        "exception_queue",
    )


def _raise_security_event(decision: AuthorizationDecision, ctx: AuthorizationContext) -> None:
    """Best-effort: a compromise verdict should reach the security observer."""
    try:
        from src.app.security.observer import emit_security_event
        emit_security_event(
            "/authorization/compromise",
            {
                "analysis": {
                    "severity": "high",
                    "event": "authorization_compromise",
                    "action": decision.action,
                    "requester": decision.requester,
                    "compromise_signals": decision.compromise_signals,
                    "terminal_outcome": decision.terminal_outcome,
                    "trace_id": ctx.trace_id,
                    "subject_id": ctx.subject_id,
                },
            },
        )
    except Exception as exc:
        _authz_log_failure("security_event", exc)


def _now_iso() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat()
