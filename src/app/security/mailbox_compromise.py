from __future__ import annotations

from typing import Any, Dict, List
import hashlib


def _hash16(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _is_high_priv_scope(scope: str) -> bool:
    s = str(scope or "").lower()
    return any(tok in s for tok in ("mail.readwrite", "mail.send", "offline_access", "files.readwrite.all", "directory.read.all"))


def analyze_mailbox_compromise(email: Dict[str, Any]) -> Dict[str, Any]:
    """Heuristic mailbox-compromise signals from provider-side mailbox activity.

    This consumes normalized mailbox activity if present in the email payload.
    """
    events = _as_list(email.get("mailbox_events")) + _as_list(email.get("mailbox_activity")) + _as_list(email.get("provider_events"))
    from_domain = str((email.get("from_addr") or "").split("@")[-1] or "").strip().lower()
    indicators: List[Dict[str, Any]] = []
    score = 0.0

    for evt in events[:120]:
        if not isinstance(evt, dict):
            continue
        et = str(evt.get("type") or evt.get("event_type") or "").strip().lower()
        action = str(evt.get("action") or "").strip().lower()
        target = str(evt.get("target") or evt.get("target_email") or evt.get("forward_to") or "").strip().lower()
        scopes = [str(x).strip().lower() for x in _as_list(evt.get("scopes"))]
        count = int(evt.get("count") or 0)

        if ("forward" in et or "forward" in action) and target:
            target_domain = target.split("@")[-1] if "@" in target else ""
            external = bool(target_domain and target_domain != from_domain)
            if external:
                score += 0.28
                indicators.append(
                    {
                        "type": "mailbox_forwarding_rule_external",
                        "value": True,
                        "reason": "Mailbox forwarding rule to external recipient",
                    }
                )
        if any(tok in et for tok in ("inbox_rule", "rule_created", "rule_updated")) and any(tok in action for tok in ("delete", "archive", "mark_read", "hide")):
            score += 0.22
            indicators.append(
                {
                    "type": "mailbox_stealth_rule",
                    "value": True,
                    "reason": "Inbox rule may hide attacker activity",
                }
            )
        if "delegate" in et and any(tok in action for tok in ("added", "granted", "create")):
            score += 0.30
            indicators.append(
                {
                    "type": "mailbox_delegate_added",
                    "value": True,
                    "reason": "Mailbox delegate access added",
                }
            )
        if ("oauth_consent" in et or "app_consent" in et) and any(_is_high_priv_scope(s) for s in scopes):
            score += 0.34
            indicators.append(
                {
                    "type": "mailbox_oauth_high_privilege_consent",
                    "value": True,
                    "reason": "New OAuth consent includes high-privilege mailbox scopes",
                }
            )
        if "impossible_travel" in et or bool(evt.get("impossible_travel")):
            score += 0.24
            indicators.append(
                {
                    "type": "mailbox_impossible_travel",
                    "value": True,
                    "reason": "Mailbox activity indicates impossible travel pattern",
                }
            )
        if any(tok in et for tok in ("mailbox_export", "mailbox_download", "directory_harvest")) or count >= 500:
            score += 0.26
            indicators.append(
                {
                    "type": "mailbox_mass_access",
                    "value": max(1, count),
                    "reason": "High-volume mailbox/directory access activity",
                }
            )

    signal_count = len(indicators)
    risk_score = round(min(1.0, score + (0.04 * min(signal_count, 6))), 4)
    compromised = bool(risk_score >= 0.65 or signal_count >= 3)
    return {
        "risk_score": risk_score,
        "compromised": compromised,
        "signal_count": signal_count,
        "events_considered": len(events[:120]),
        "source_hash": _hash16(str(email.get("message_id") or "")),
        "indicators": indicators,
    }

