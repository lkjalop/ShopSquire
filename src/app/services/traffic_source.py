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


def _coarsen_network(net: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Coarsen a fraud-grade IP enrichment ({asn, country, is_hosting, is_vpn, is_tor, geo_risk}) into a
    NON-PII, retention-safe network fingerprint: {asn, country, risk_tier}. The raw IP is NEVER stored — an
    ASN is a public network operator shared by thousands-to-millions of endpoints (coarse by construction),
    a 2-letter country is region-grade, and risk_tier is a derived bucket. This is what lets marketing BI
    segment by region/network and lets security cluster abusive ASNs after the fact — without holding an IP.
    Returns None when there's nothing coarse to keep."""
    if not isinstance(net, dict) or not net:
        return None
    asn = net.get("asn")
    country = str(net.get("country") or "").strip().upper()[:2] or None
    # IDEMPOTENT: honour an already-coarsened tier so re-coarsening a coarse dict is a no-op (the raw
    # is_vpn/is_tor flags are gone by then). Only derive from raw enrichment flags when no tier is set.
    risk_tier = str(net.get("risk_tier") or "").strip().lower()
    if not risk_tier:
        if net.get("is_tor"):
            risk_tier = "high"
        elif net.get("is_hosting") or net.get("is_vpn"):
            risk_tier = "medium"
        else:
            risk_tier = str(net.get("geo_risk") or "low").strip().lower() or "low"
    out: Dict[str, Any] = {"risk_tier": risk_tier}
    if isinstance(asn, int) and asn > 0:
        out["asn"] = asn
    if country and country != "ZZ":
        out["country"] = country
    return out


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
            bot_suspect: bool = False, occurred_at: Optional[str] = None, tenant_id: str = "default",
            network: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Best-effort capture at the consumer-signals ingest: record the session's first-touch channel + emit a
    market signal — a `demand` per unique session (a visit), and a `conversion` (tagged with that session's
    channel) when the action is a purchase. ``bot_suspect`` (a datacenter/VPN/Tor visit — the same fraud-grade
    network flag, repurposed) tags the visit so VERIFIED-HUMAN visits can be counted (bot-clean traffic quality
    most SMB analytics can't produce). Feeds detect_channel_performance. Returns {channel, emitted}."""
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
            demand_payload: Dict[str, Any] = {"session": session_hash, "channel": channel,
                                              "bot_suspect": bool(bot_suspect)}
            coarse = _coarsen_network(network)
            if coarse:
                demand_payload["net"] = coarse   # {asn, country, risk_tier} — coarse + non-PII (never the IP)
            sig = normalize(signal_type="demand", source="traffic_source",
                            payload=demand_payload,
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
    human: Dict[str, int] = {}       # visits that are NOT datacenter/VPN/Tor (verified-human)
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
            if not (payload or {}).get("bot_suspect"):
                human[ch] = human.get(ch, 0) + 1
    out["channels"] = sorted(
        ({"channel": c, "visits": visits.get(c, 0), "verified_human_visits": human.get(c, 0),
          "conversions": conv.get(c, 0),
          "conversion_rate": round(conv.get(c, 0) / visits[c], 4) if visits.get(c) else 0.0}
         for c in set(list(visits) + list(conv))), key=lambda r: -r["visits"])
    tv, th = sum(visits.values()), sum(human.values())
    out["summary"] = {"total_visits": tv, "verified_human_visits": th, "bot_suspect_visits": tv - th,
                      "human_ratio": round(th / tv, 4) if tv else 0.0, "conversions": sum(conv.values())}
    try:
        out["findings"] = [f.summary for f in detect_channel_performance(signals, min_volume=1)]
    except Exception:
        pass
    return out


def network_breakdown(db, *, tenant_id: str = "default", limit: int = 5000) -> Dict[str, Any]:
    """The BI + security view of the coarsened network fingerprint carried on `demand` signals. Aggregates
    visits by COUNTRY (marketing region segmentation) and by ASN (security cluster forensics) and by
    RISK_TIER — all from the non-PII {asn, country, risk_tier} embedded at capture. Read-only; never touches
    a raw IP (there isn't one to touch). Empty structure on error."""
    out: Dict[str, Any] = {"by_country": [], "by_asn": [], "by_risk_tier": [], "coverage": {}}
    try:
        rows = db.execute(text(
            "SELECT payload_json FROM market_signal WHERE tenant_id=:t AND source='traffic_source' "
            "AND signal_type='demand' ORDER BY ingested_at DESC LIMIT :lim"),
            {"t": str(tenant_id or "default"), "lim": int(limit)}).fetchall()
    except Exception as exc:
        logger.debug("network_breakdown query failed: %s", exc)
        return out
    import json as _json
    by_country: Dict[str, Dict[str, int]] = {}
    by_asn: Dict[int, Dict[str, int]] = {}
    by_risk: Dict[str, int] = {}
    total = enriched = 0
    for (pj,) in (rows or []):
        try:
            payload = pj if isinstance(pj, dict) else _json.loads(pj or "{}")
        except Exception:
            payload = {}
        total += 1
        human = 0 if (payload or {}).get("bot_suspect") else 1
        net = (payload or {}).get("net") if isinstance((payload or {}).get("net"), dict) else None
        if not net:
            continue
        enriched += 1
        c = str(net.get("country") or "").upper()
        if c:
            b = by_country.setdefault(c, {"visits": 0, "verified_human_visits": 0})
            b["visits"] += 1; b["verified_human_visits"] += human
        a = net.get("asn")
        if isinstance(a, int) and a > 0:
            b = by_asn.setdefault(a, {"visits": 0, "verified_human_visits": 0})
            b["visits"] += 1; b["verified_human_visits"] += human
        rt = str(net.get("risk_tier") or "low")
        by_risk[rt] = by_risk.get(rt, 0) + 1
    out["by_country"] = sorted(({"country": c, **v} for c, v in by_country.items()), key=lambda r: -r["visits"])[:50]
    out["by_asn"] = sorted(({"asn": a, **v} for a, v in by_asn.items()), key=lambda r: -r["visits"])[:50]
    out["by_risk_tier"] = sorted(({"risk_tier": k, "visits": v} for k, v in by_risk.items()), key=lambda r: -r["visits"])
    out["coverage"] = {"demand_signals": total, "with_network": enriched,
                       "coverage_ratio": round(enriched / total, 4) if total else 0.0}
    return out
