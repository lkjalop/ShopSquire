"""Market Analysis Engine (M3, agnostic CORE) — market_signal → typed findings.

Consumes recent market_signal rows (the Module-1 stream) and produces business-relevant
MarketFindings via DETERMINISTIC detectors — no LLM in finding generation (the deck: roll out
explainable detection first, before complex techniques). Reuses the existing AnomalyDetector for the
statistical leg (injectable for tests). Findings are PROPOSALS for the hippograph + dashboards; they
never act (any action re-enters policy → escalation → audit).

Detectors (v1, explainable):
  • demand_shift             — daily search/demand volume spike or slowdown vs baseline
  • conversion_anomaly       — daily conversion-rate (conversions/demand) DROP anomaly
  • inventory_demand_mismatch — recurring demand with zero result_count (catalog not meeting demand;
                                a proxy until a real inventory adapter sharpens it)
  • demand_forecast          — FORWARD-looking: project next-period demand (EWMA, the leg
                                DemandForecaster falls back to) → flag a projected surge / shortfall
  • seasonal_demand          — day-of-week pattern: a recurring weekday whose mean demand exceeds the
                                overall daily mean (seasonality)
  • competitor_undercut      — a competitor price below ours on the same entity (pricing-review signal)
  • objection_cluster        — recurring support objections on the same theme (objection mining)
  • segment_shift            — Phase 4: a segment whose demand SHARE shifted vs baseline (re-targeting)
  • channel_performance      — Phase 4: a channel under/over-performing vs the cross-channel mean
  • bundle_opportunity       — Phase 4: a frequently co-purchased SKU pair (bundle candidate)

Vertical-blind: finding_type/entity_ref/evidence are opaque to product vocabulary. Never raises.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

FINDING_DEMAND_SHIFT = "demand_shift"
FINDING_CONVERSION_ANOMALY = "conversion_anomaly"
FINDING_INVENTORY_MISMATCH = "inventory_demand_mismatch"
FINDING_DEMAND_FORECAST = "demand_forecast"
FINDING_SEASONAL_DEMAND = "seasonal_demand"
FINDING_COMPETITOR_UNDERCUT = "competitor_undercut"
FINDING_OBJECTION_CLUSTER = "objection_cluster"
FINDING_FUNNEL_DROPOFF = "funnel_dropoff"
FINDING_SEGMENT_SHIFT = "segment_shift"  # Phase 4: WHO is buying is shifting (re-targeting signal)
FINDING_CHANNEL_PERFORMANCE = "channel_performance"  # Phase 4: a channel under/over-performing vs the mean
FINDING_BUNDLE_OPPORTUNITY = "bundle_opportunity"    # Phase 4: a frequently co-purchased pair → bundle

_MIN_POINTS = 4  # need enough history before an anomaly finding is actionable
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class MarketFinding:
    finding_type: str
    entity_ref: Optional[str]   # sku / query token / category / None
    severity: str               # info | warn | critical
    confidence: float           # 0..1
    summary: str                # plain-English, evidence-grounded (no LLM)
    evidence: Dict[str, Any] = field(default_factory=dict)
    window: str = "recent"


def _day(occurred_at: Any) -> str:
    return str(occurred_at or "")[:10]  # YYYY-MM-DD bucket


def _default_anomaly_fn(series: List[float], domain: str):
    from src.app.services.anomaly_detector import AnomalyDetector
    return AnomalyDetector().score_series(series=series, domain=domain)


def _top_anomaly(results: Any):
    """The highest-confidence anomalous result, robust to score_series' return alignment."""
    anomalous = [r for r in (results or []) if getattr(r, "is_anomaly", False)]
    if not anomalous:
        return None
    return max(anomalous, key=lambda r: float(getattr(r, "confidence", 0.0) or 0.0))


def detect_demand_shift(signals, *, anomaly_fn: Optional[Callable] = None, min_points: int = _MIN_POINTS) -> List[MarketFinding]:
    fn = anomaly_fn or _default_anomaly_fn
    by_day: Dict[str, int] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "demand":
            continue
        d = _day(s.get("occurred_at"))
        if d:
            by_day[d] = by_day.get(d, 0) + 1
    days = sorted(by_day)
    if len(days) < min_points:
        return []
    series = [float(by_day[d]) for d in days]
    top = _top_anomaly(fn(series, "market_demand"))
    if not top:
        return []
    latest = series[-1]
    base = sum(series[:-1]) / max(1, len(series) - 1)
    direction = "spike" if latest >= base else "slowdown"
    return [MarketFinding(
        FINDING_DEMAND_SHIFT, None, str(getattr(top, "severity", "warn")), float(getattr(top, "confidence", 0.5)),
        f"Search demand {direction}: {int(latest)} vs ~{base:.0f} baseline.",
        # direction is CARRIED in evidence so a downstream proposal demotes a slowdown instead of
        # boosting it (shadow_actions._direction_for reads evidence['direction']).
        {"latest": latest, "baseline": round(base, 2), "direction": direction,
         "z_score": getattr(top, "z_score", None), "days": days[-min_points:]},
        "daily",
    )]


def detect_conversion_anomaly(signals, *, anomaly_fn: Optional[Callable] = None, min_points: int = _MIN_POINTS) -> List[MarketFinding]:
    fn = anomaly_fn or _default_anomaly_fn
    conv: Dict[str, int] = {}
    demand: Dict[str, int] = {}
    for s in signals or []:
        st = (s or {}).get("signal_type")
        d = _day(s.get("occurred_at"))
        if not d:
            continue
        if st == "conversion":
            conv[d] = conv.get(d, 0) + 1
        elif st == "demand":
            demand[d] = demand.get(d, 0) + 1
    days = sorted(set(conv) | set(demand))
    if len(days) < min_points:
        return []
    series = [conv.get(d, 0) / max(1.0, float(demand.get(d, 0) or 1)) for d in days]
    top = _top_anomaly(fn(series, "market_conversion"))
    if not top:
        return []
    latest = series[-1]
    base = sum(series[:-1]) / max(1, len(series) - 1)
    if latest >= base:
        return []  # only a DROP is the actionable signal (a rise is good news)
    return [MarketFinding(
        FINDING_CONVERSION_ANOMALY, None, str(getattr(top, "severity", "warn")), float(getattr(top, "confidence", 0.5)),
        f"Conversion-rate drop: {latest:.2f} vs ~{base:.2f} baseline.",
        {"latest": round(latest, 4), "baseline": round(base, 4), "z_score": getattr(top, "z_score", None)},
        "daily",
    )]


# buyer-search text becomes a customer-visible finding summary (LLM narration in live mode). NEUTRALISE it:
# strip control chars/newlines (kills newline-based injection), collapse + cap length (kills long payloads),
# and redact obvious injection phrases. Defence-in-depth — the summary is quoted DATA, never an instruction.
_INJECTION_RE = re.compile(
    r"ignore\s+(previous|above|all|prior)|system\s+prompt|jailbreak|disregard|override\s+(policy|instructions)|"
    r"you\s+are\s+now|new\s+instructions|forget\s+(everything|the\s+above)", re.IGNORECASE)


def _neutralize_query(q: Any) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(q or ""))   # strip control chars / newlines
    s = re.sub(r"\s+", " ", s).strip()[:80]               # collapse whitespace + cap length
    return "[redacted: suspicious search]" if _INJECTION_RE.search(s) else s


def detect_inventory_demand_mismatch(signals, *, min_unmet: int = 3) -> List[MarketFinding]:
    """Zero-result searches → a catalog-gap finding. HARDENED against poisoning: gated on DISTINCT USERS (not
    raw search count), so one actor scripting a query can't manufacture a customer-visible finding; and the
    query string is NEUTRALISED before it becomes the (LLM-narrated) summary. An anonymous zero-result search
    (no uid/session) never counts toward a finding."""
    unmet: Dict[str, set] = {}   # neutralised query -> set of DISTINCT hashed identities
    for s in signals or []:
        if (s or {}).get("signal_type") != "demand":
            continue
        p = s.get("payload") or {}
        rc = p.get("result_count")
        q = str(p.get("query") or "").strip().lower()
        if not (q and rc is not None and int(rc) <= 0):
            continue
        ident = str(p.get("uid_hash") or p.get("session") or "").strip()
        if not ident:
            continue  # an unidentified zero-result search cannot manufacture a finding (anti-flood)
        unmet.setdefault(_neutralize_query(q), set()).add(ident)
    out: List[MarketFinding] = []
    for q, idents in sorted(unmet.items(), key=lambda x: (-len(x[1]), x[0])):
        n = len(idents)
        if n < min_unmet:
            continue
        severity = "warn" if n < min_unmet * 2 else "critical"
        out.append(MarketFinding(
            FINDING_INVENTORY_MISMATCH, q, severity, min(1.0, n / float(min_unmet * 3)),
            f"Unmet demand: '{q}' searched by {n} distinct users with no results (catalog gap).",
            {"query": q, "distinct_users": n, "provenance": "buyer_search_unverified"}, "recent",
        ))
    return out


def _daily_demand(signals) -> Dict[str, int]:
    """Bucket demand signals into a {YYYY-MM-DD: count} series (shared by the demand detectors)."""
    by_day: Dict[str, int] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "demand":
            continue
        d = _day(s.get("occurred_at"))
        if d:
            by_day[d] = by_day.get(d, 0) + 1
    return by_day


def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _safe_weekday(d: Any) -> Optional[int]:
    from datetime import date as _date
    try:
        return _date.fromisoformat(str(d)).weekday()
    except Exception:
        return None


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _ewma_forecast(series: List[float], *, alpha: float = 0.28):
    """One-step-ahead EWMA projection — the dependency-free leg DemandForecaster itself falls back to.
    Returns (prediction, method)."""
    if not series:
        return 0.0, "ewma_default"
    x = float(series[0])
    for v in series[1:]:
        x = alpha * float(v) + (1.0 - alpha) * x
    return max(0.0, x), "ewma"


def detect_demand_forecast(signals, *, forecast_fn: Optional[Callable] = None, min_points: int = _MIN_POINTS,
                           surge_ratio: float = 1.25, shortfall_ratio: float = 0.75) -> List[MarketFinding]:
    """FORWARD-looking: project next-period demand from the daily series and flag a material projected
    surge or shortfall. ``forecast_fn(series)->(pred, method)`` is injectable (default EWMA). Carries
    direction in evidence so a downstream proposal boosts a projected surge / demotes a projected
    shortfall (same contract as demand_shift)."""
    fc = forecast_fn or _ewma_forecast
    by_day = _daily_demand(signals)
    days = sorted(by_day)
    if len(days) < min_points:
        return []
    series = [float(by_day[d]) for d in days]
    baseline = sum(series) / len(series)
    if baseline <= 0:
        return []
    pred, method = fc(series)
    ratio = pred / baseline
    if ratio >= surge_ratio:
        direction, sev = "spike", ("critical" if ratio >= surge_ratio * 1.6 else "warn")
    elif ratio <= shortfall_ratio:
        direction, sev = "slowdown", ("critical" if ratio <= shortfall_ratio * 0.6 else "warn")
    else:
        return []  # projection within the normal band → nothing to flag
    return [MarketFinding(
        FINDING_DEMAND_FORECAST, None, sev, round(min(1.0, abs(ratio - 1.0) / 0.5), 3),
        f"Projected demand {direction}: ~{pred:.0f} next vs ~{baseline:.0f} baseline.",
        {"projected": round(pred, 2), "baseline": round(baseline, 2), "direction": direction,
         "ratio": round(ratio, 3), "method": method, "horizon": "next_period"},
        "forecast",
    )]


def detect_seasonal_demand(signals, *, min_days: int = 7, min_occurrences: int = 2,
                           min_ratio: float = 1.4) -> List[MarketFinding]:
    """Day-of-week pattern: flag the recurring weekday whose mean demand materially exceeds the overall
    daily mean. Needs >= min_days of history and the peak weekday observed >= min_occurrences times.
    Vertical-blind (weekday is a calendar label, never product vocabulary)."""
    by_day = _daily_demand(signals)
    days = sorted(by_day)
    if len(days) < min_days:
        return []
    per_wd: Dict[int, List[float]] = {}
    for d in days:
        wd = _safe_weekday(d)
        if wd is not None:
            per_wd.setdefault(wd, []).append(float(by_day[d]))
    counts = [float(by_day[d]) for d in days]
    overall = sum(counts) / len(counts)
    cand = [(wd, sum(v) / len(v)) for wd, v in per_wd.items() if len(v) >= min_occurrences]
    if overall <= 0 or not cand:
        return []
    peak_wd, peak_mean = max(cand, key=lambda x: x[1])
    ratio = peak_mean / overall
    if ratio < min_ratio:
        return []
    sev = "warn" if ratio >= min_ratio * 1.5 else "info"  # a pattern, not an incident
    return [MarketFinding(
        FINDING_SEASONAL_DEMAND, None, sev, round(min(1.0, ratio - 1.0), 3),
        f"Demand peaks on {_WEEKDAYS[peak_wd]}: ~{peak_mean:.0f} vs ~{overall:.0f} overall.",
        {"peak_weekday": _WEEKDAYS[peak_wd], "peak_mean": round(peak_mean, 2),
         "overall_mean": round(overall, 2), "ratio": round(ratio, 3)},
        "weekly",
    )]


def detect_competitor_undercut(signals, *, min_gap_pct: float = 0.05) -> List[MarketFinding]:
    """A competitor price below ours by >= min_gap_pct on the SAME entity → a pricing-review finding,
    using the latest observation per entity. payload: {entity_ref|sku, our_price_cents,
    competitor_price_cents, competitor?}. Vertical-blind (entity_ref is opaque)."""
    latest: Dict[str, Dict[str, Any]] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "competitor":
            continue
        p = s.get("payload") or {}
        ent = str(p.get("entity_ref") or p.get("sku") or "").strip()
        if not ent:
            continue
        prev = latest.get(ent)
        if prev is None or str(s.get("occurred_at") or "") >= str(prev.get("_occ") or ""):
            latest[ent] = {**p, "_occ": s.get("occurred_at")}
    out: List[MarketFinding] = []
    for ent, p in sorted(latest.items()):
        ours = _safe_float(p.get("our_price_cents"))
        theirs = _safe_float(p.get("competitor_price_cents"))
        if not ours or not theirs or ours <= 0 or theirs <= 0 or theirs >= ours:
            continue
        gap = (ours - theirs) / ours
        if gap < min_gap_pct:
            continue
        out.append(MarketFinding(
            FINDING_COMPETITOR_UNDERCUT, ent, "critical" if gap >= 0.15 else "warn",
            round(min(1.0, gap / 0.3), 3),
            f"Competitor undercut on '{ent}': {theirs:.0f}c vs our {ours:.0f}c ({gap * 100:.0f}% lower).",
            {"our_price_cents": ours, "competitor_price_cents": theirs, "gap_pct": round(gap, 4),
             "competitor": p.get("competitor")},
            "recent",
        ))
    return out


def detect_objection_cluster(signals, *, min_count: int = 3) -> List[MarketFinding]:
    """Recurring support objections on the same theme → a finding (objection mining). payload:
    {theme|reason|token}. Vertical-blind (theme is an opaque label)."""
    by_theme: Dict[str, int] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "support_objection":
            continue
        p = s.get("payload") or {}
        theme = str(p.get("theme") or p.get("reason") or p.get("token") or "").strip().lower()
        if theme:
            by_theme[theme] = by_theme.get(theme, 0) + 1
    out: List[MarketFinding] = []
    for theme, n in sorted(by_theme.items(), key=lambda x: (-x[1], x[0])):
        if n < min_count:
            continue
        out.append(MarketFinding(
            FINDING_OBJECTION_CLUSTER, theme, "critical" if n >= min_count * 2 else "warn",
            round(min(1.0, n / float(min_count * 3)), 3),
            f"Recurring objection '{theme}': raised {n}x.",
            {"theme": theme, "count": n}, "recent",
        ))
    return out


def detect_funnel_dropoff(signals, *, min_rate: float = 0.5, min_volume: int = 10) -> List[MarketFinding]:
    """A purchase-funnel stage losing a high fraction of the buyers who reached it → a finding. payload:
    {stage, entered, abandoned} (aggregated across rows per stage). Vertical-blind (stage is an opaque
    label). Only flags a stage with enough volume so a tiny sample can't trip it."""
    by_stage: Dict[str, List[int]] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "funnel":
            continue
        p = s.get("payload") or {}
        stage = str(p.get("stage") or "").strip().lower()
        entered = _safe_int(p.get("entered"))
        abandoned = _safe_int(p.get("abandoned"))
        if stage and entered is not None and abandoned is not None:
            agg = by_stage.setdefault(stage, [0, 0])
            agg[0] += max(0, entered)
            agg[1] += max(0, abandoned)
    out: List[MarketFinding] = []
    for stage, (entered, abandoned) in sorted(by_stage.items(), key=lambda kv: (-kv[1][1], kv[0])):
        if entered < min_volume:
            continue
        rate = abandoned / entered if entered else 0.0
        if rate < min_rate:
            continue
        out.append(MarketFinding(
            FINDING_FUNNEL_DROPOFF, stage, "critical" if rate >= 0.75 else "warn", round(min(1.0, rate), 3),
            f"High drop-off at '{stage}': {rate * 100:.0f}% abandoned ({abandoned}/{entered}).",
            {"stage": stage, "entered": entered, "abandoned": abandoned, "rate": round(rate, 4)}, "recent",
        ))
    return out


def detect_segment_shift(signals, *, min_points: int = _MIN_POINTS, min_total: int = 20,
                         min_abs_shift: float = 0.15) -> List[MarketFinding]:
    """Phase 4 — segment mix shift. Buckets demand SHARE by segment over the window and flags a segment
    whose latest-day share deviates from its earlier-days baseline share by >= min_abs_shift: a shift in
    WHO is buying (a re-targeting signal). ``segment`` is an OPAQUE payload label (vertical-blind); the
    detector is explainable + deterministic (no LLM). Shadow-only: it yields a finding, never an action.

    Guards: needs >= min_points days and >= min_total demand signals carrying a segment, so a thin or
    segment-less stream produces nothing (no spurious re-targeting on noise)."""
    by_day_seg: Dict[str, Dict[str, int]] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "demand":
            continue
        d = _day(s.get("occurred_at"))
        seg = str((s.get("payload") or {}).get("segment") or "").strip().lower()
        if not d or not seg:
            continue
        bucket = by_day_seg.setdefault(d, {})
        bucket[seg] = bucket.get(seg, 0) + 1
    days = sorted(by_day_seg)
    if len(days) < min_points:
        return []
    segments = sorted({seg for day in by_day_seg.values() for seg in day})
    totals = {seg: sum(by_day_seg[d].get(seg, 0) for d in days) for seg in segments}
    if sum(totals.values()) < min_total:
        return []
    earlier, latest_day = days[:-1], days[-1]
    latest_total = sum(by_day_seg[latest_day].values()) or 1

    def _baseline_share(seg: str) -> float:
        num = sum(by_day_seg[d].get(seg, 0) for d in earlier)
        den = sum(sum(by_day_seg[d].values()) for d in earlier)
        return (num / den) if den else 0.0

    out: List[MarketFinding] = []
    for seg in segments:
        base_share = _baseline_share(seg)
        latest_share = by_day_seg[latest_day].get(seg, 0) / latest_total
        shift = latest_share - base_share
        if abs(shift) < min_abs_shift:
            continue
        direction = "rising" if shift > 0 else "falling"
        severity = "critical" if abs(shift) >= 0.30 else "warn"
        out.append(MarketFinding(
            FINDING_SEGMENT_SHIFT, seg, severity, round(min(1.0, abs(shift) / 0.5), 3),
            f"Segment '{seg}' demand share {direction}: {latest_share * 100:.0f}% latest vs "
            f"~{base_share * 100:.0f}% baseline.",
            {"segment": seg, "latest_share": round(latest_share, 4), "baseline_share": round(base_share, 4),
             "shift": round(shift, 4), "direction": direction, "segment_total": totals[seg]},
            "daily",
        ))
    out.sort(key=lambda f: -f.confidence)
    return out


def detect_channel_performance(signals, *, min_volume: int = 20, min_rate_gap: float = 0.30) -> List[MarketFinding]:
    """Phase 4 — per-channel conversion performance. For each channel with >= min_volume demand, computes
    conversion rate (conversions/demand) and flags a channel whose rate deviates from the cross-channel mean
    by >= min_rate_gap (relative): an under/over-performing channel — a channel-prioritization signal.
    ``channel`` is an OPAQUE payload label (vertical-blind); explainable + deterministic (no LLM).
    Shadow-only: a finding, never an action.

    Guards: needs >= 2 channels each clearing min_volume, so a thin or single-channel stream is quiet."""
    conv: Dict[str, int] = {}
    demand: Dict[str, int] = {}
    for s in signals or []:
        st = (s or {}).get("signal_type")
        ch = str(((s or {}).get("payload") or {}).get("channel") or "").strip().lower()
        if not ch:
            continue
        if st == "conversion":
            conv[ch] = conv.get(ch, 0) + 1
        elif st == "demand":
            demand[ch] = demand.get(ch, 0) + 1
    channels = [c for c in demand if demand[c] >= min_volume]
    if len(channels) < 2:
        return []
    rates = {c: conv.get(c, 0) / demand[c] for c in channels}
    mean = sum(rates.values()) / len(rates)
    if mean <= 0:
        return []
    out: List[MarketFinding] = []
    for c in sorted(channels):
        gap = (rates[c] - mean) / mean
        if abs(gap) < min_rate_gap:
            continue
        direction = "overperforming" if gap > 0 else "underperforming"
        severity = "critical" if (gap < 0 and abs(gap) >= 0.5) else "warn"
        out.append(MarketFinding(
            FINDING_CHANNEL_PERFORMANCE, c, severity, round(min(1.0, abs(gap)), 3),
            f"Channel '{c}' {direction}: {rates[c] * 100:.1f}% conversion vs {mean * 100:.1f}% mean.",
            {"channel": c, "rate": round(rates[c], 4), "mean_rate": round(mean, 4), "gap": round(gap, 4),
             "direction": direction, "demand": demand[c]}, "recent",
        ))
    out.sort(key=lambda f: -f.confidence)
    return out


def detect_bundle_opportunity(signals, *, min_co_occurrence: int = 3, top_k: int = 5) -> List[MarketFinding]:
    """Phase 4 — co-purchase mining. Counts product PAIRS that appear together in the same order and flags
    pairs co-occurring >= min_co_occurrence times: a bundle opportunity. Reads ``order`` signals whose
    payload carries an ``items`` list of opaque SKU labels (vertical-blind); deterministic + explainable.
    Shadow-only: a finding, never an action. Returns the top_k strongest pairs."""
    from itertools import combinations
    pairs: Dict[tuple, int] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "order":
            continue
        items = ((s or {}).get("payload") or {}).get("items")
        if not isinstance(items, list):
            continue
        skus = sorted({str(i).strip() for i in items if str(i).strip()})
        for a, b in combinations(skus, 2):
            pairs[(a, b)] = pairs.get((a, b), 0) + 1
    flagged = [(p, n) for p, n in pairs.items() if n >= min_co_occurrence]
    if not flagged:
        return []
    flagged.sort(key=lambda kv: (-kv[1], kv[0]))
    out: List[MarketFinding] = []
    for (a, b), n in flagged[:top_k]:
        out.append(MarketFinding(
            FINDING_BUNDLE_OPPORTUNITY, f"{a}+{b}", "info", round(min(1.0, n / 10.0), 3),
            f"Bundle opportunity: '{a}' + '{b}' co-purchased {n} times.",
            {"pair": [a, b], "co_occurrence": n, "direction": "bundle"}, "recent",
        ))
    return out


def _safe(fn: Callable, *args, **kw) -> List[MarketFinding]:
    try:
        return fn(*args, **kw)
    except Exception:
        return []  # one detector failing must not sink the rest


def analyze(signals, *, anomaly_fn: Optional[Callable] = None,
            forecast_fn: Optional[Callable] = None) -> List[MarketFinding]:
    """Run every detector over a market_signal window. Never raises."""
    out: List[MarketFinding] = []
    out += _safe(detect_demand_shift, signals, anomaly_fn=anomaly_fn)
    out += _safe(detect_conversion_anomaly, signals, anomaly_fn=anomaly_fn)
    out += _safe(detect_inventory_demand_mismatch, signals)
    out += _safe(detect_demand_forecast, signals, forecast_fn=forecast_fn)
    out += _safe(detect_seasonal_demand, signals)
    out += _safe(detect_competitor_undercut, signals)
    out += _safe(detect_objection_cluster, signals)
    out += _safe(detect_funnel_dropoff, signals)
    out += _safe(detect_segment_shift, signals)
    out += _safe(detect_channel_performance, signals)
    out += _safe(detect_bundle_opportunity, signals)
    return out


def load_recent_signals(db, *, limit: int = 2000, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read recent market_signal rows into the dict shape the detectors expect. When ``tenant_id`` is
    given, only that tenant's signals are read (keeps a real run free of replay-demo data). Best-effort."""
    if db is None:
        return []
    try:
        sql = "SELECT signal_type, source, payload_json, occurred_at FROM market_signal "
        params: Dict[str, Any] = {"lim": int(limit)}
        if tenant_id is not None:
            sql += "WHERE COALESCE(tenant_id,'default') = :t "
            params["t"] = str(tenant_id)
        rows = db.execute(text(sql + "ORDER BY occurred_at DESC LIMIT :lim"), params).fetchall()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            payload = json.loads(r[2]) if r[2] else {}
        except Exception:
            payload = {}
        out.append({"signal_type": r[0], "source": r[1],
                    "payload": payload if isinstance(payload, dict) else {}, "occurred_at": r[3]})
    return out


def run_analysis(db, *, limit: int = 2000, anomaly_fn: Optional[Callable] = None,
                 forecast_fn: Optional[Callable] = None, tenant_id: Optional[str] = None) -> List[MarketFinding]:
    """Load recent market_signal rows + analyze them. The DB entry point for the BATCH task. Pass
    ``tenant_id`` to analyze only that tenant's signals (a real run excludes replay-demo).

    NOTE: analysis runs the real statistical models (~1.6s) — batch-only, never the request path.
    The hot path reads PERSISTED findings via load_recent_findings()."""
    return analyze(load_recent_signals(db, limit=limit, tenant_id=tenant_id),
                   anomaly_fn=anomaly_fn, forecast_fn=forecast_fn)


# ── findings persistence (batch writes, hot path reads) ──────────────────────
# Lifecycle: a fresh batch run SUPERSEDES the prior active finding for the same (tenant, type, entity,
# window) — so re-running analysis updates rather than duplicates, and load returns only status='active'
# (or human-'corrected' rows kept as a learning record, never auto-overwritten).
SCHEMA_VERSION = 1
DEFAULT_TENANT = "default"

_FINDING_DDL = """
CREATE TABLE IF NOT EXISTS market_finding (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    schema_version INTEGER DEFAULT 1,
    finding_type TEXT,
    entity_ref TEXT,
    severity TEXT,
    confidence REAL,
    summary TEXT,
    evidence_json TEXT,
    "window" TEXT,
    dedup_key TEXT,
    status TEXT DEFAULT 'active',
    corrected_by_human INTEGER DEFAULT 0,
    correction_note TEXT,
    superseded_by TEXT,
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
# Columns added after the table first shipped — applied to pre-existing tables on upgrade.
_FINDING_UPGRADE_COLS = (
    ("tenant_id", "TEXT DEFAULT 'default'"),
    ("schema_version", "INTEGER DEFAULT 1"),
    ("dedup_key", "TEXT"),
    ("status", "TEXT DEFAULT 'active'"),
    ("corrected_by_human", "INTEGER DEFAULT 0"),
    ("correction_note", "TEXT"),
    ("superseded_by", "TEXT"),
)
_FINDING_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_market_finding_type ON market_finding(finding_type)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_detected ON market_finding(detected_at)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_dedup ON market_finding(tenant_id, dedup_key, status)",
)


def _finding_dedup_key(tenant_id: str, finding_type: str, entity_ref: Any, window: str) -> str:
    import hashlib
    raw = "|".join([str(tenant_id), str(finding_type), str(entity_ref or ""), str(window or "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


import weakref as _weakref

_FINDING_COLS_INTROSPECTED = _weakref.WeakSet()  # engines whose finding-column upgrade has run


def _ensure_finding_columns(db) -> None:
    """Add post-ship columns to a pre-existing market_finding (portable upgrade; no failing DDL).
    Reflection memoized per-engine so load_recent_findings() (hot path) doesn't pay get_columns()
    every call — fresh tables already have every column; a real upgrade runs once."""
    from sqlalchemy import inspect as _sa_inspect
    try:
        bind = db.get_bind()
    except Exception:
        bind = None
    if bind is not None and bind in _FINDING_COLS_INTROSPECTED:
        return
    try:
        # session's OWN connection, not the engine — a pooled checkout would roll back pending inserts.
        have = {c["name"] for c in _sa_inspect(db.connection()).get_columns("market_finding")}
    except Exception:
        return  # table not present yet → don't memoize, retry next call
    for name, decl in _FINDING_UPGRADE_COLS:
        if name not in have:
            db.execute(text(f"ALTER TABLE market_finding ADD COLUMN {name} {decl}"))
    if bind is not None:
        _FINDING_COLS_INTROSPECTED.add(bind)


def ensure_finding_table(db) -> None:
    db.execute(text(_FINDING_DDL))
    _ensure_finding_columns(db)
    for stmt in _FINDING_INDEXES:
        db.execute(text(stmt))


def persist_findings(db, findings: List[MarketFinding], *, tenant_id: str = DEFAULT_TENANT,
                     expire_unobserved: bool = False) -> int:
    """Write a batch run's findings, SUPERSEDING the prior active finding per (tenant,type,entity,window)
    so re-runs update rather than accumulate. Human-corrected rows are left untouched (the human wins).

    When ``expire_unobserved`` is set (the batch passes it), any ACTIVE machine finding whose key was
    NOT produced by THIS run is marked 'expired' — so a finding for an anomaly that has since
    disappeared does not stay active forever (a later run that no longer sees it retires it). Returns
    the count written. Best-effort; never raises."""
    if db is None:
        return 0
    findings = findings or []
    try:
        import json
        import uuid

        from sqlalchemy import bindparam
        ensure_finding_table(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        observed: List[str] = []
        n = 0
        for f in findings:
            dk = _finding_dedup_key(tid, f.finding_type, f.entity_ref, f.window)
            observed.append(dk)
            new_id = str(uuid.uuid4())
            # supersede the prior active machine finding for this key (never a human-corrected one)
            db.execute(
                text("UPDATE market_finding SET status='superseded', superseded_by=:nid "
                     "WHERE tenant_id=:t AND dedup_key=:dk AND status='active' "
                     "AND COALESCE(corrected_by_human,0)=0"),
                {"nid": new_id, "t": tid, "dk": dk},
            )
            db.execute(
                text("INSERT INTO market_finding (id, tenant_id, schema_version, finding_type, entity_ref, "
                     "severity, confidence, summary, evidence_json, \"window\", dedup_key, status) "
                     "VALUES (:i,:tn,:sv,:t,:e,:s,:c,:m,:j,:w,:dk,'active')"),
                {"i": new_id, "tn": tid, "sv": int(SCHEMA_VERSION), "t": f.finding_type, "e": f.entity_ref,
                 "s": f.severity, "c": float(f.confidence), "m": f.summary,
                 "j": json.dumps(f.evidence, default=str), "w": f.window, "dk": dk},
            )
            n += 1
        if expire_unobserved:
            # retire active machine findings this run did NOT re-observe (anomaly gone). With no
            # observations at all, every active machine finding is retired.
            if observed:
                stmt = text("UPDATE market_finding SET status='expired' WHERE tenant_id=:t "
                            "AND status='active' AND COALESCE(corrected_by_human,0)=0 "
                            "AND dedup_key NOT IN :keys").bindparams(bindparam("keys", expanding=True))
                db.execute(stmt, {"t": tid, "keys": observed})
            else:
                db.execute(text("UPDATE market_finding SET status='expired' WHERE tenant_id=:t "
                                "AND status='active' AND COALESCE(corrected_by_human,0)=0"), {"t": tid})
        return n
    except Exception:
        return 0


def correct_finding(db, finding_id: str, *, note: str = "", tenant_id: str = DEFAULT_TENANT) -> bool:
    """Human-in-the-loop correction: flag a finding as human-corrected so future batch runs never
    silently overwrite it. The correction becomes a learning signal (projected as a weighted hippograph
    edge by the human-correction learner). Returns True when a row was updated. Never raises."""
    if db is None or not finding_id:
        return False
    try:
        ensure_finding_table(db)
        res = db.execute(
            text("UPDATE market_finding SET corrected_by_human=1, status='corrected', correction_note=:n "
                 "WHERE id=:i AND tenant_id=:t"),
            {"n": str(note or ""), "i": str(finding_id), "t": str(tenant_id).strip() or DEFAULT_TENANT},
        )
        return bool(getattr(res, "rowcount", 0) or 0)
    except Exception:
        return False


def load_recent_findings(db, *, limit: int = 50, tenant_id: str = DEFAULT_TENANT) -> List[MarketFinding]:
    """Read recent ACTIVE persisted findings (fast — the hot-path read), tenant-scoped. Superseded and
    human-corrected rows are excluded from the live read. Best-effort."""
    if db is None:
        return []
    try:
        ensure_finding_table(db)
        rows = db.execute(
            text("SELECT finding_type, entity_ref, severity, confidence, summary, evidence_json, \"window\" "
                 "FROM market_finding "
                 "WHERE COALESCE(status,'active')='active' AND COALESCE(tenant_id,'default')=:t "
                 "ORDER BY detected_at DESC LIMIT :lim"),
            {"lim": int(limit), "t": str(tenant_id).strip() or DEFAULT_TENANT},
        ).fetchall()
    except Exception:
        return []
    import json
    out: List[MarketFinding] = []
    for r in rows:
        try:
            ev = json.loads(r[5]) if r[5] else {}
        except Exception:
            ev = {}
        out.append(MarketFinding(r[0], r[1], r[2], float(r[3] or 0.0), r[4] or "",
                                 ev if isinstance(ev, dict) else {}, r[6] or "recent"))
    return out
