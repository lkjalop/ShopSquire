from __future__ import annotations

from typing import Any, Dict, List


_KEV_BY_CONTEXT: Dict[str, List[str]] = {
    "lolbin": ["CVE-2021-40444", "CVE-2023-36884"],
    "network_probe": ["CVE-2021-41773", "CVE-2021-42013", "CVE-2021-44228"],
    "prompt_injection": ["CVE-2024-3094"],
}


def _dread(avg: float) -> Dict[str, Any]:
    # Keep a compact, deterministic profile for demo and policy use.
    avg = max(0.0, min(10.0, float(avg)))
    return {
        "damage": round(min(10.0, avg + 1.0), 2),
        "reproducibility": round(avg, 2),
        "exploitability": round(min(10.0, avg + 0.5), 2),
        "affected_users": round(max(1.0, avg - 0.5), 2),
        "discoverability": round(min(10.0, avg + 0.75), 2),
        "avg": round(avg, 2),
    }


def _cvss(base_score: float) -> Dict[str, Any]:
    score = max(0.0, min(10.0, float(base_score)))
    sev = "low"
    if score >= 9.0:
        sev = "critical"
    elif score >= 7.0:
        sev = "high"
    elif score >= 4.0:
        sev = "medium"
    return {"score": round(score, 2), "severity": sev, "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:M"}


def enrich_context(context: str, *, signals: List[str] | None = None, kill_chain_stage: str | None = None) -> Dict[str, Any]:
    ctx = str(context or "generic").strip().lower()
    sig = {str(x).strip().lower() for x in (signals or []) if str(x).strip()}
    stage = str(kill_chain_stage or "").strip() or None

    mitre: List[str] = []
    base_dread = 5.2
    base_cvss = 6.8
    if ctx == "lolbin":
        mitre = ["T1218", "T1059.001", "T1105"]
        base_dread = 7.8
        base_cvss = 8.1
        stage = stage or "Exploitation"
    elif ctx == "network_probe":
        mitre = ["T1595", "T1590", "T1046"]
        base_dread = 6.4
        base_cvss = 7.2
        stage = stage or "Recon"
    elif ctx == "prompt_injection":
        mitre = ["AML.T0043", "T1566.002"]
        base_dread = 7.2
        base_cvss = 7.6
        stage = stage or "Delivery"
    else:
        mitre = ["T1595"]
        stage = stage or "Recon"

    if "denylisted_ioc" in sig or "prompt_injection" in sig:
        base_dread += 0.8
        base_cvss += 0.6
    if "oob_verification_required" in sig:
        base_dread += 0.6
    if "path_fuzzing" in sig or "scanner_burst" in sig:
        base_dread += 0.7
        base_cvss += 0.5

    return {
        "context": ctx,
        "kill_chain_stage": stage,
        "mitre_attack": mitre,
        "dread": _dread(base_dread),
        "cvss": _cvss(base_cvss),
        "kev": _KEV_BY_CONTEXT.get(ctx, [])[:3],
    }


def infer_kill_chain_stage(*, event_type: str | None = None, signals: List[str] | None = None) -> str:
    et = str(event_type or "").lower()
    s = {str(x).lower() for x in (signals or [])}
    if "network_probe" in et or "path_fuzzing" in s or "scanner_burst" in s:
        return "Recon"
    if "email" in et or "attachment" in s:
        return "Delivery"
    if "lolbin" in s or "prompt_injection" in s:
        return "Exploitation"
    if "c2" in s:
        return "CommandAndControl"
    if "exfiltration" in s:
        return "ActionsOnObjectives"
    return "Weaponization"
