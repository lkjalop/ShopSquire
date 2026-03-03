"""Behavioral biometrics fraud detection module.

Analyzes mouse movement, typing cadence, and tap timing patterns to
distinguish legitimate human users from bots, scripts, and account-takeover
sessions.  Signals feed into the FraudScorer as additional weighted inputs.

Expected session_data keys (populated by frontend telemetry):
  - mouse_events: list of {x, y, t_ms} dicts
  - keystroke_events: list of {key, down_ms, up_ms} dicts
  - tap_events: list of {x, y, t_ms, pressure?} dicts (mobile)
  - scroll_events: list of {delta_y, t_ms} dicts
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class BiometricResult:
    """Aggregated biometric analysis result."""
    is_bot_likely: bool = False
    risk_score: float = 0.0  # 0.0 (human) – 1.0 (bot)
    signals: Dict[str, bool] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Constants & thresholds (tuned from research baselines)
# ---------------------------------------------------------------------------
_MIN_MOUSE_EVENTS = 8
_MIN_KEYSTROKE_EVENTS = 5
_MIN_TAP_EVENTS = 4

# Mouse: bots tend to have perfectly straight lines and constant velocity
_STRAIGHTNESS_THRESHOLD = 0.98     # ratio of displacement / path length
_VELOCITY_CV_THRESHOLD = 0.05      # coefficient of variation of velocity
_MOUSE_JITTER_THRESHOLD = 0.5      # px — bots have near-zero jitter

# Typing: bots have very low variance in inter-key delay
_TYPING_CV_THRESHOLD = 0.08        # coefficient of variation of hold times
_TYPING_RHYTHM_THRESHOLD = 0.10    # CV of flight times (key-to-key)
_TYPING_TOO_FAST_MS = 25           # median flight time below this → inhuman

# Tap: bots have perfectly uniform timing
_TAP_INTERVAL_CV_THRESHOLD = 0.06
_TAP_TOO_FAST_MS = 80              # faster than 80ms between taps → bot

# Scroll: bots often scroll in perfectly uniform increments
_SCROLL_UNIFORMITY_THRESHOLD = 0.95


# ---------------------------------------------------------------------------
# Helper math
# ---------------------------------------------------------------------------
def _cv(values: Sequence[float]) -> float:
    """Coefficient of variation (std / mean).  Returns 0.0 on degenerate input."""
    if len(values) < 2:
        return 0.0
    m = statistics.mean(values)
    if m == 0:
        return 0.0
    return statistics.stdev(values) / abs(m)


def _euclidean(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


# ---------------------------------------------------------------------------
# Mouse analysis
# ---------------------------------------------------------------------------
def analyze_mouse(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze mouse movement trajectory for bot indicators.

    Returns dict with straightness_ratio, velocity_cv, jitter, is_suspicious.
    """
    if not events or len(events) < _MIN_MOUSE_EVENTS:
        return {"sufficient_data": False}

    # Sort by timestamp
    pts = sorted(events, key=lambda e: float(e.get("t_ms") or 0))

    # Path length and displacement
    path_len = 0.0
    velocities: List[float] = []
    angular_changes: List[float] = []
    prev_angle: Optional[float] = None

    for i in range(1, len(pts)):
        x1, y1, t1 = float(pts[i - 1].get("x", 0)), float(pts[i - 1].get("y", 0)), float(pts[i - 1].get("t_ms", 0))
        x2, y2, t2 = float(pts[i].get("x", 0)), float(pts[i].get("y", 0)), float(pts[i].get("t_ms", 0))
        seg = _euclidean(x1, y1, x2, y2)
        path_len += seg
        dt = max(t2 - t1, 1.0)
        velocities.append(seg / dt)

        # Angle change
        angle = math.atan2(y2 - y1, x2 - x1)
        if prev_angle is not None:
            diff = abs(angle - prev_angle)
            if diff > math.pi:
                diff = 2 * math.pi - diff
            angular_changes.append(diff)
        prev_angle = angle

    displacement = _euclidean(
        float(pts[0].get("x", 0)), float(pts[0].get("y", 0)),
        float(pts[-1].get("x", 0)), float(pts[-1].get("y", 0)),
    )
    straightness = (displacement / path_len) if path_len > 0 else 1.0

    # Jitter: mean angular change (bots → near zero)
    jitter = statistics.mean(angular_changes) if angular_changes else 0.0
    vel_cv = _cv(velocities)

    suspicious = (
        straightness >= _STRAIGHTNESS_THRESHOLD
        and vel_cv < _VELOCITY_CV_THRESHOLD
        and jitter < _MOUSE_JITTER_THRESHOLD
    )

    return {
        "sufficient_data": True,
        "straightness_ratio": round(straightness, 4),
        "velocity_cv": round(vel_cv, 4),
        "jitter": round(jitter, 4),
        "path_length": round(path_len, 2),
        "displacement": round(displacement, 2),
        "event_count": len(pts),
        "is_suspicious": suspicious,
    }


# ---------------------------------------------------------------------------
# Typing cadence analysis
# ---------------------------------------------------------------------------
def analyze_typing(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze keystroke dynamics for bot/ATO indicators.

    Expects events with {key, down_ms, up_ms} where down_ms/up_ms are
    absolute timestamps (ms since page load).
    """
    if not events or len(events) < _MIN_KEYSTROKE_EVENTS:
        return {"sufficient_data": False}

    sorted_evt = sorted(events, key=lambda e: float(e.get("down_ms") or 0))

    hold_times: List[float] = []
    flight_times: List[float] = []

    for i, evt in enumerate(sorted_evt):
        down = float(evt.get("down_ms") or 0)
        up = float(evt.get("up_ms") or 0)
        hold = max(up - down, 0)
        hold_times.append(hold)

        if i > 0:
            prev_up = float(sorted_evt[i - 1].get("up_ms") or 0)
            flight = max(down - prev_up, 0)
            flight_times.append(flight)

    hold_cv = _cv(hold_times)
    flight_cv = _cv(flight_times) if flight_times else 0.0
    median_flight = statistics.median(flight_times) if flight_times else 999.0

    suspicious = (
        (hold_cv < _TYPING_CV_THRESHOLD and flight_cv < _TYPING_RHYTHM_THRESHOLD)
        or median_flight < _TYPING_TOO_FAST_MS
    )

    return {
        "sufficient_data": True,
        "hold_time_cv": round(hold_cv, 4),
        "flight_time_cv": round(flight_cv, 4),
        "median_flight_ms": round(median_flight, 2),
        "mean_hold_ms": round(statistics.mean(hold_times), 2) if hold_times else 0,
        "event_count": len(sorted_evt),
        "is_suspicious": suspicious,
    }


# ---------------------------------------------------------------------------
# Tap timing analysis (mobile)
# ---------------------------------------------------------------------------
def analyze_taps(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze tap patterns for mobile bot detection."""
    if not events or len(events) < _MIN_TAP_EVENTS:
        return {"sufficient_data": False}

    sorted_taps = sorted(events, key=lambda e: float(e.get("t_ms") or 0))
    intervals: List[float] = []
    for i in range(1, len(sorted_taps)):
        t1 = float(sorted_taps[i - 1].get("t_ms") or 0)
        t2 = float(sorted_taps[i].get("t_ms") or 0)
        intervals.append(max(t2 - t1, 0))

    interval_cv = _cv(intervals)
    median_interval = statistics.median(intervals) if intervals else 999.0

    # Pressure variance (if available)
    pressures = [float(e.get("pressure") or 0.5) for e in sorted_taps if e.get("pressure") is not None]
    pressure_cv = _cv(pressures) if len(pressures) >= _MIN_TAP_EVENTS else None

    suspicious = (
        interval_cv < _TAP_INTERVAL_CV_THRESHOLD
        or median_interval < _TAP_TOO_FAST_MS
    )

    result: Dict[str, Any] = {
        "sufficient_data": True,
        "interval_cv": round(interval_cv, 4),
        "median_interval_ms": round(median_interval, 2),
        "event_count": len(sorted_taps),
        "is_suspicious": suspicious,
    }
    if pressure_cv is not None:
        result["pressure_cv"] = round(pressure_cv, 4)
    return result


# ---------------------------------------------------------------------------
# Scroll uniformity analysis
# ---------------------------------------------------------------------------
def analyze_scroll(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect perfectly uniform scrolling (bot indicator)."""
    if not events or len(events) < 4:
        return {"sufficient_data": False}

    deltas = [abs(float(e.get("delta_y") or 0)) for e in events if e.get("delta_y") is not None]
    if len(deltas) < 4:
        return {"sufficient_data": False}

    # Check if all deltas are identical (or near-identical)
    mode = statistics.mode(deltas) if deltas else 0
    uniform_ratio = sum(1 for d in deltas if abs(d - mode) < 1.0) / len(deltas)

    return {
        "sufficient_data": True,
        "uniform_ratio": round(uniform_ratio, 4),
        "is_suspicious": uniform_ratio >= _SCROLL_UNIFORMITY_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Combined session analysis → fraud signals
# ---------------------------------------------------------------------------
def analyze_session_biometrics(session_data: Dict[str, Any]) -> BiometricResult:
    """Run all biometric checks on session telemetry data.

    Returns a BiometricResult with is_bot_likely, risk_score (0-1), and
    individual signal flags suitable for injection into FraudScorer.
    """
    signals: Dict[str, bool] = {}
    details: Dict[str, Any] = {}
    risk_components: List[float] = []

    # Mouse
    mouse_events = session_data.get("mouse_events") or []
    mouse = analyze_mouse(mouse_events)
    details["mouse"] = mouse
    if mouse.get("sufficient_data"):
        if mouse.get("is_suspicious"):
            signals["biometric_mouse_bot_pattern"] = True
            risk_components.append(0.85)
        else:
            signals["biometric_mouse_bot_pattern"] = False
            risk_components.append(0.1)

    # Typing
    keystroke_events = session_data.get("keystroke_events") or []
    typing = analyze_typing(keystroke_events)
    details["typing"] = typing
    if typing.get("sufficient_data"):
        if typing.get("is_suspicious"):
            signals["biometric_typing_bot_pattern"] = True
            risk_components.append(0.80)
        else:
            signals["biometric_typing_bot_pattern"] = False
            risk_components.append(0.1)

    # Taps (mobile)
    tap_events = session_data.get("tap_events") or []
    taps = analyze_taps(tap_events)
    details["taps"] = taps
    if taps.get("sufficient_data"):
        if taps.get("is_suspicious"):
            signals["biometric_tap_bot_pattern"] = True
            risk_components.append(0.75)
        else:
            signals["biometric_tap_bot_pattern"] = False
            risk_components.append(0.1)

    # Scroll
    scroll_events = session_data.get("scroll_events") or []
    scroll = analyze_scroll(scroll_events)
    details["scroll"] = scroll
    if scroll.get("sufficient_data"):
        if scroll.get("is_suspicious"):
            signals["biometric_scroll_uniform"] = True
            risk_components.append(0.60)
        else:
            signals["biometric_scroll_uniform"] = False
            risk_components.append(0.1)

    # Aggregate
    if risk_components:
        risk_score = sum(risk_components) / len(risk_components)
    else:
        risk_score = 0.0

    is_bot = risk_score >= 0.55

    return BiometricResult(
        is_bot_likely=is_bot,
        risk_score=round(min(1.0, risk_score), 4),
        signals=signals,
        details=details,
    )
