"""Bounded fraud context assembly for recommendation turns."""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any


def evaluate_recommendation_fraud(
    *,
    tls_fingerprints: dict[str, Any] | None,
    source_ip: str | None,
    image_hash: str | None,
    trace_id: str | None,
    scorer: Any,
    geoip_fn: Callable[[str], dict[str, Any]] | None = None,
    previous_country: str | None = None,
    billing_country: str | None = None,
    trace_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build typed session evidence and score it without hiding source failures."""
    tls = tls_fingerprints if isinstance(tls_fingerprints, dict) else {}
    effective_ip = str(tls.get("source_ip") or source_ip or "").strip()
    session: dict[str, Any] = {}
    if effective_ip:
        session.update({"source_ip": effective_ip, "ip": effective_ip})
    ja3 = str(tls.get("ja3_hash") or "").strip().lower()
    ja4 = str(tls.get("ja4_hash") or "").strip().lower()
    if ja3:
        session["ja3_hash"] = ja3[:128]
    if ja4:
        session["ja4_hash"] = ja4[:128]
    known_ja3 = [
        item.strip().lower()
        for item in os.getenv("FRAUD_KNOWN_JA3_HASHES", "").split(",")
        if item.strip()
    ]
    known_ja4 = [
        item.strip().lower()
        for item in os.getenv("FRAUD_KNOWN_JA4_HASHES", "").split(",")
        if item.strip()
    ]
    if known_ja3:
        session["known_fraud_ja3_hashes"] = known_ja3
    if known_ja4:
        session["known_fraud_ja4_hashes"] = known_ja4
    errors: list[dict[str, str]] = []
    if effective_ip and geoip_fn is not None:
        try:
            geo = geoip_fn(effective_ip) or {}
            if geo.get("country"):
                session["ip_country"] = str(geo["country"]).upper()
            if geo.get("asn") is not None:
                session["asn"] = int(geo["asn"])
            session["geo_risk"] = float(geo.get("risk") or 0.0)
        except (RuntimeError, TypeError, ValueError) as exc:
            errors.append({
                "stage": "fraud_session.geoip",
                "error": str(exc)[:240],
            })
    if previous_country:
        session["previous_ip_country"] = str(previous_country).upper()[:2]
    if billing_country:
        session["billing_country"] = str(billing_country).upper()[:2]
    score, level, signals = scorer.score_with_enrichment(
        base_signals={},
        expected_serial=None,
        observed_serial=None,
        image_phash=str(image_hash or ""),
        session_data=session,
        case_id=trace_id,
    )
    summary = {
        "score": round(float(score), 4),
        "level": str(level),
        "signals": signals,
        "ja3_hash": ja3 or None,
        "ja4_hash": ja4 or None,
        "source_ip": effective_ip or None,
        "ip_country": session.get("ip_country"),
        "asn": session.get("asn"),
    }
    if trace_fn is not None:
        for error in errors:
            trace_fn(
                trace_id=trace_id,
                event_type="system_error",
                source_type="system",
                source_id="Recommend_Agent",
                target_type="system",
                target_id=None,
                payload=error,
            )
        trace_fn(
            trace_id=trace_id,
            event_type="fraud_score",
            source_type="agent",
            source_id="Fraud_Scoring_Agent",
            target_type="system",
            target_id=None,
            payload=summary,
        )
    return {
        "summary": summary,
        "session_data": session,
        "persistence": {
            "last_ip_country": session.get("ip_country"),
            "last_asn": session.get("asn"),
        },
        "errors": errors,
    }
