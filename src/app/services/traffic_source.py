"""Traffic-source attribution (agnostic CORE) — the marketing-BI foundation.

The single biggest gap vs GA4/Segment/Shopify analytics was that ShopSquire captured NO traffic source: no
utm_*, gclid/fbclid, or referrer. So the market-analysis channel/segment detectors (which already exist) had
nothing to key on. This module closes that: it canonicalises a visit's traffic source into an opaque CHANNEL
label, records the session→channel, and emits market signals (a `demand` per unique visiting session, a
`conversion` when that session converts) tagged with the channel — feeding the already-built
market_analysis.detect_channel_performance ("which channel converts best") + the attribution backbone.

Vertical-blind: `channel` is an opaque traffic label (google/cpc, referral:example.com, direct, paid:…) — no
product vocabulary. Best-effort; never raises into the ingest path.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy import text

logger = logging.getLogger("shopsquire.traffic_source")

_CONVERSION_ACTIONS = {"purchase", "order", "checkout", "checkout_complete", "conversion", "buy", "order_placed"}
_SAFE = re.compile(r"[^a-z0-9.:/_-]+", re.IGNORECASE)

_DDL = """
CREATE TABLE IF NOT EXISTS traffic_source_session (
    tenant_id     TEXT,
    session_hash  TEXT,
    channel       TEXT,
    first_seen    TEXT,
    PRIMARY KEY (tenant_id, session_hash)
)
"""


def _slug(s: Any) -> str:
    return _SAFE.sub("-", str(s or "").strip().lower()).strip("-")


def _referrer_domain(referrer: Optional[str]) -> str:
    try:
        host = urlparse(str(referrer or "")).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def canonical_channel(*, utm_source: Any = None, utm_medium: Any = None, referrer: Any = None,
                      gclid: Any = None, fbclid: Any = None) -> str:
    """Derive one opaque CHANNEL label from a visit's attribution params. Priority: explicit UTM > paid-click
    id > referrer domain > 'direct'. Pure — the inputs are opaque strings; the labels are traffic categories,
    not product vocabulary."""
    src = _slug(utm_source)
    med = _slug(utm_medium)
    if src:
        return f"{src}/{med}" if med else src
    if _slug(gclid):
        return "paid:google"
    if _slug(fbclid):
        return "paid:meta"
    dom = _referrer_domain(referrer)
    if dom:
        return f"referral:{dom}"
    return "direct"


def parse_from_properties(properties: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Pull the attribution params out of an event's (already-sanitised) properties bag. Tolerant of nesting
    under a 'utm'/'attribution' sub-dict. Returns {channel, utm_source, utm_medium, utm_campaign, referrer}."""
    p = properties if isinstance(properties, dict) else {}
    sub = p.get("utm") if isinstance(p.get("utm"), dict) else (p.get("attribution") if isinstance(p.get("attribution"), dict) else {})

    def g(*keys):
        for k in keys:
            if p.get(k) not in (None, ""):
                return p.get(k)
            if isinstance(sub, dict) and sub.get(k) not in (None, ""):
                return sub.get(k)
        return None

    utm_source, utm_medium = g("utm_source", "source"), g("utm_medium", "medium")
    utm_campaign, referrer = g("utm_campaign", "campaign"), g("referrer", "referer", "ref")
    channel = canonical_channel(utm_source=utm_source, utm_medium=utm_medium, referrer=referrer,
                                gclid=g("gclid"), fbclid=g("fbclid"))
    return {"channel": channel, "utm_source": utm_source, "utm_medium": utm_medium,
            "utm_campaign": utm_campaign, "referrer": referrer}


def _record_session_channel(db, *, tenant_id: str, session_hash: str, channel: str, now_iso: Optional[str]) -> None:
    """Stamp session→channel ONCE (first-touch). A later conversion on the same session reads this back."""
    db.execute(text(_DDL))
    exists = db.execute(text("SELECT channel FROM traffic_source_session WHERE tenant_id=:t AND session_hash=:s"),
                        {"t": tenant_id, "s": session_hash}).fetchone()
    if exists:
        return
    db.execute(text("INSERT INTO traffic_source_session (tenant_id, session_hash, channel, first_seen) "
                    "VALUES (:t,:s,:c,:f)"), {"t": tenant_id, "s": session_hash, "c": channel, "f": now_iso or ""})


def channel_for_session(db, *, tenant_id: str, session_hash: str) -> Optional[str]:
    try:
        db.execute(text(_DDL))
        row = db.execute(text("SELECT channel FROM traffic_source_session WHERE tenant_id=:t AND session_hash=:s"),
                         {"t": tenant_id, "s": session_hash}).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception:
        return None


def capture(db, *, session_hash: Optional[str], properties: Optional[Dict[str, Any]], action: Optional[str] = None,
            occurred_at: Optional[str] = None, tenant_id: str = "default") -> Dict[str, Any]:
    """Best-effort capture at the consumer-signals ingest: record the session's first-touch channel + emit a
    market signal — a `demand` per unique session (a visit), and a `conversion` (tagged with that session's
    channel) when the action is a purchase. Feeds detect_channel_performance. Returns {channel, emitted}."""
    if db is None or not session_hash:
        return {"channel": None, "emitted": None}
    tid = str(tenant_id or "default")
    try:
        from src.app.services.market_signal import ingest, normalize
        parsed = parse_from_properties(properties)
        channel = parsed["channel"]
        is_conv = str(action or "").strip().lower() in _CONVERSION_ACTIONS
        db.execute(text(_DDL))
        _record_session_channel(db, tenant_id=tid, session_hash=session_hash, channel=channel, now_iso=occurred_at)
        if is_conv:
            # attribute the conversion to the session's FIRST-touch channel (not the possibly-'direct' return)
            channel = channel_for_session(db, tenant_id=tid, session_hash=session_hash) or channel
            sig = normalize(signal_type="conversion", source="traffic_source",
                            payload={"session": session_hash, "channel": channel, "campaign": parsed.get("utm_campaign")},
                            occurred_at=occurred_at, trust_score=1.0, dedup_fields=["session", "channel"],
                            tenant_id=tid)
            emitted = "conversion"
        else:
            sig = normalize(signal_type="demand", source="traffic_source",
                            payload={"session": session_hash, "channel": channel},
                            occurred_at=occurred_at, trust_score=0.8, dedup_fields=["session", "channel"],
                            tenant_id=tid)
            emitted = "demand"
        if sig:
            ingest(db, sig, min_trust=0.0)
        db.commit()
        return {"channel": channel, "emitted": emitted}
    except Exception as exc:
        logger.debug("traffic_source.capture skipped: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"channel": None, "emitted": None}


def channel_breakdown(db, *, tenant_id: str = "default", limit: int = 5000) -> Dict[str, Any]:
    """The marketing-BI view: visits + conversions + conversion-rate per channel (from the traffic_source
    signals) + the channel-performance findings. Read-only; [] on error."""
    out = {"channels": [], "findings": []}
    try:
        from src.app.services.market_analysis import detect_channel_performance, load_recent_findings
        rows = db.execute(text(
            "SELECT signal_type, payload_json FROM market_signal WHERE tenant_id=:t AND source='traffic_source' "
            "ORDER BY ingested_at DESC LIMIT :lim"), {"t": str(tenant_id or "default"), "lim": int(limit)}).fetchall()
    except Exception as exc:
        logger.debug("channel_breakdown query failed: %s", exc)
        return out
    import json as _json
    visits: Dict[str, int] = {}
    conv: Dict[str, int] = {}
    signals: List[Dict[str, Any]] = []
    for st, pj in (rows or []):
        try:
            payload = pj if isinstance(pj, dict) else _json.loads(pj or "{}")
        except Exception:
            payload = {}
        ch = str((payload or {}).get("channel") or "").strip().lower()
        if not ch:
            continue
        signals.append({"signal_type": st, "payload": payload})
        if st == "conversion":
            conv[ch] = conv.get(ch, 0) + 1
        elif st == "demand":
            visits[ch] = visits.get(ch, 0) + 1
    out["channels"] = sorted(
        ({"channel": c, "visits": visits.get(c, 0), "conversions": conv.get(c, 0),
          "conversion_rate": round(conv.get(c, 0) / visits[c], 4) if visits.get(c) else 0.0}
         for c in set(list(visits) + list(conv))), key=lambda r: -r["visits"])
    try:
        out["findings"] = [f.summary for f in detect_channel_performance(signals, min_volume=1)]
    except Exception:
        pass
    return out
