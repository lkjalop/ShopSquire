"""Retargeting trigger — detects high-value cart abandonment and emits events.

Monitors cart sessions that have gone idle beyond a configurable threshold
and produces retargeting signals that downstream systems (email, push,
campaign correlator) can consume.

No new infrastructure required — reads from the existing ``orders`` /
``draft_orders`` table and publishes via the decision trace + optional
webhook.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

_log = logging.getLogger("shopsquire.retargeting_trigger")

# Defaults (overridable via env)
_IDLE_THRESHOLD_SEC = int(os.getenv("CART_IDLE_THRESHOLD_SEC", "1800"))  # 30 min
_HIGH_VALUE_CENTS = int(os.getenv("CART_HIGH_VALUE_CENTS", "80000"))     # $800

_WEBHOOKS_YML = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "webhooks.yml")


def _load_retargeting_webhook_urls() -> List[str]:
    """Read retargeting_events URLs from config/webhooks.yml. Returns [] on any error."""
    try:
        import yaml  # type: ignore
        with open(_WEBHOOKS_YML, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        urls = cfg.get("webhooks", {}).get("retargeting_events") or []
        return [str(u) for u in urls if u and isinstance(u, str)]
    except Exception:
        _log.debug("_load_retargeting_webhook_urls: could not read webhooks.yml", exc_info=True)
        return []


@dataclass
class AbandonmentSignal:
    """Describes a detected cart-abandonment event."""
    session_id: str
    uid_hash: Optional[str] = None
    cart_value_cents: int = 0
    cart_skus: List[str] = field(default_factory=list)
    idle_seconds: float = 0.0
    inferred_persona: Optional[str] = None
    use_case_key: Optional[str] = None
    channel: str = "web"
    suggested_action: str = "retarget_email"  # retarget_email | retarget_push | nudge_inline
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_cart_abandonment(
    *,
    session_id: str,
    uid_hash: Optional[str] = None,
    cart_skus: List[str],
    cart_value_cents: int,
    last_activity_ts: float,
    persona: Optional[str] = None,
    use_case_key: Optional[str] = None,
    channel: str = "web",
    idle_threshold_sec: Optional[int] = None,
    high_value_cents: Optional[int] = None,
) -> Optional[AbandonmentSignal]:
    """Evaluate whether a cart session qualifies for retargeting.

    Returns an ``AbandonmentSignal`` if the cart is idle + high-value,
    else ``None``.  Pure function — no DB writes.
    """
    threshold = idle_threshold_sec if idle_threshold_sec is not None else _IDLE_THRESHOLD_SEC
    hv_floor = high_value_cents if high_value_cents is not None else _HIGH_VALUE_CENTS

    idle_sec = time.time() - last_activity_ts
    if idle_sec < threshold:
        return None
    if cart_value_cents < hv_floor:
        return None

    # Determine suggested action
    action = "retarget_email"
    if idle_sec < threshold * 2:
        action = "nudge_inline"   # still possibly on-site
    elif channel in ("app", "mobile"):
        action = "retarget_push"

    # Confidence heuristic: higher for longer idle + higher cart value
    conf = min(0.95, 0.5 + (idle_sec / (threshold * 6)) + (cart_value_cents / 500000))

    return AbandonmentSignal(
        session_id=session_id,
        uid_hash=uid_hash,
        cart_value_cents=cart_value_cents,
        cart_skus=list(cart_skus),
        idle_seconds=round(idle_sec, 1),
        inferred_persona=persona,
        use_case_key=use_case_key,
        channel=channel,
        suggested_action=action,
        confidence=round(conf, 3),
    )


def emit_abandonment_event(
    signal: AbandonmentSignal,
    *,
    trace_id: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> Optional[str]:
    """Persist the abandonment signal to the decision trace and record a commerce outcome.

    Returns the outcome decision_id or None on failure.
    """
    try:
        from src.app.services.decision_log import log_trace_event, record_commerce_outcome

        # 1. Emit a trace event for observability dashboards
        if trace_id:
            log_trace_event(
                trace_id=trace_id,
                event_type="cart_abandonment_detected",
                source_type="retargeting_trigger",
                source_id="retargeting_trigger",
                target_type="session",
                target_id=signal.session_id,
                payload=signal.to_dict(),
            )

        # 2. If there's a parent decision_id, close it with abandonment outcome
        outcome_id = None
        if decision_id:
            outcome_id = record_commerce_outcome(
                decision_id,
                abandonment=True,
                intervention_type=signal.suggested_action,
                extra={
                    "cart_value_cents": signal.cart_value_cents,
                    "idle_seconds": signal.idle_seconds,
                    "cart_skus": signal.cart_skus,
                    "inferred_persona": signal.inferred_persona,
                },
            )

        # 3. Dispatch to configured retargeting webhook endpoints (fire-and-forget)
        _dispatch_retargeting_webhooks(signal, decision_id=decision_id, trace_id=trace_id)

        return outcome_id
    except Exception:
        _log.exception("emit_abandonment_event failed for session=%s", signal.session_id)
        return None


def _dispatch_retargeting_webhooks(
    signal: AbandonmentSignal,
    *,
    decision_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    """Enqueue webhook deliveries for every configured retargeting_events URL."""
    urls = _load_retargeting_webhook_urls()
    if not urls:
        return
    try:
        from src.app.services.webhook_dispatcher import enqueue_webhook
    except Exception:
        _log.debug("_dispatch_retargeting_webhooks: webhook_dispatcher unavailable", exc_info=True)
        return

    payload = {
        "event": "cart_abandonment_detected",
        "session_id": signal.session_id,
        "uid_hash": signal.uid_hash,
        "cart_value_cents": signal.cart_value_cents,
        "cart_skus": signal.cart_skus,
        "idle_seconds": signal.idle_seconds,
        "inferred_persona": signal.inferred_persona,
        "use_case_key": signal.use_case_key,
        "channel": signal.channel,
        "suggested_action": signal.suggested_action,
        "confidence": signal.confidence,
        "decision_id": decision_id,
        "trace_id": trace_id,
    }
    for url in urls:
        try:
            delivery_id = str(uuid.uuid4())
            enqueue_webhook(delivery_id, url, payload)
            _log.debug("retargeting webhook enqueued id=%s url=%s session=%s", delivery_id, url, signal.session_id)
        except Exception:
            _log.warning("retargeting webhook enqueue failed for url=%s", url, exc_info=True)


def scan_idle_carts(
    active_sessions: List[Dict[str, Any]],
    *,
    idle_threshold_sec: Optional[int] = None,
    high_value_cents: Optional[int] = None,
) -> List[AbandonmentSignal]:
    """Batch-scan a list of active session dicts for abandonment candidates.

    Each session dict should have keys:
        session_id, uid_hash, cart_skus, cart_value_cents, last_activity_ts,
        and optionally: persona, use_case_key, channel.

    Returns list of AbandonmentSignal for sessions that qualify.
    """
    signals: List[AbandonmentSignal] = []
    for sess in active_sessions:
        try:
            sig = evaluate_cart_abandonment(
                session_id=str(sess.get("session_id") or ""),
                uid_hash=sess.get("uid_hash"),
                cart_skus=list(sess.get("cart_skus") or []),
                cart_value_cents=int(sess.get("cart_value_cents") or 0),
                last_activity_ts=float(sess.get("last_activity_ts") or 0),
                persona=sess.get("persona"),
                use_case_key=sess.get("use_case_key"),
                channel=str(sess.get("channel") or "web"),
                idle_threshold_sec=idle_threshold_sec,
                high_value_cents=high_value_cents,
            )
            if sig:
                signals.append(sig)
        except Exception:
            _log.debug("scan_idle_carts: skipping session %s", sess.get("session_id"), exc_info=True)
    return signals
