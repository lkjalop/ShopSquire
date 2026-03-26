from __future__ import annotations

import os
from typing import Any, Dict

from src.app.security.threat_intel_url import (
    check_url_threat_intel,
    enqueue_url_threat_intel,
    get_cached_url_threat_intel,
)


def derive_qr_legitimacy_details(
    sig: Dict[str, Any] | None,
    *,
    policy_route: str,
) -> Dict[str, Any]:
    s = sig if isinstance(sig, dict) else {}
    payloads = s.get("qr_payloads") if isinstance(s.get("qr_payloads"), list) else []
    redirect_probe = s.get("qr_redirect_probe") if isinstance(s.get("qr_redirect_probe"), dict) else {}
    destination_url = ""
    for row in payloads:
        if not isinstance(row, dict):
            continue
        data = str(row.get("data") or "").strip()
        if data.lower().startswith(("http://", "https://")):
            destination_url = data
            break
    if not destination_url:
        destination_url = str(redirect_probe.get("chain", [None])[0] or "").strip()
    final_url = str(redirect_probe.get("final_url") or destination_url or "").strip()
    hops = int(redirect_probe.get("hops") or 0)

    qr_external = bool(s.get("qr_external_url_detected") or s.get("qr_external_url"))
    qr_injection = bool(s.get("qr_prompt_injection"))
    qr_detected = bool(s.get("qr_code_detected"))
    qr_benign = bool(s.get("qr_benign_detected"))

    if policy_route == "lockdown" or qr_injection:
        verdict = "malicious"
    elif qr_external:
        verdict = "suspicious"
    elif qr_detected and qr_benign:
        verdict = "benign"
    elif qr_detected:
        verdict = "suspicious"
    else:
        verdict = "benign"

    confidence = 0.35 + (0.2 if qr_detected else 0.0) + (0.15 if destination_url else 0.0) + (0.1 if hops > 0 else 0.0)
    if qr_external:
        confidence += 0.1
    if qr_injection:
        confidence += 0.15

    intel = None
    intel_pending = False
    intel_sources = []
    intel_risk = None
    intel_enabled = str(os.getenv("QR_THREAT_INTEL_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
    intel_async = str(os.getenv("QR_THREAT_INTEL_ASYNC", "1")).strip().lower() in {"1", "true", "yes", "on"}
    intel_sync_timeout_route = str(os.getenv("QR_THREAT_INTEL_SYNC", "0")).strip().lower() in {"1", "true", "yes", "on"}
    if intel_enabled and destination_url:
        try:
            intel = get_cached_url_threat_intel(destination_url)
            if not intel:
                if intel_async:
                    queued = enqueue_url_threat_intel(destination_url)
                    intel_pending = bool(queued.get("queued") or queued.get("inflight"))
                elif intel_sync_timeout_route:
                    intel = check_url_threat_intel(destination_url, use_cache=True)
        except Exception:
            intel = None
        if isinstance(intel, dict):
            intel_risk = float(intel.get("risk") or 0.0)
            intel_sources = [str((r or {}).get("source") or "") for r in (intel.get("sources") or []) if isinstance(r, dict)]
            if bool(intel.get("malicious")) or intel_risk >= 0.75:
                verdict = "malicious"
            elif intel_risk >= 0.35 and verdict != "malicious":
                verdict = "suspicious"
            confidence += min(0.2, max(0.0, intel_risk * 0.25))

    return {
        "destination_url": destination_url or None,
        "final_url": final_url or None,
        "redirect_hops": hops,
        "reputation_verdict": verdict,
        "confidence": round(min(0.98, max(0.05, confidence)), 2),
        "intel_pending": bool(intel_pending),
        "intel_risk": round(float(intel_risk), 3) if isinstance(intel_risk, float) else None,
        "intel_sources": [x for x in intel_sources if x][:5],
    }
