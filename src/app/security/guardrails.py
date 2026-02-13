from __future__ import annotations

import re
import hashlib
import json
from typing import Any, Dict, List, Tuple

from src.app.config import load_feature_flags, get_settings
from src.app.security.utils import normalize_digits, is_card_like


SERIAL_PATTERNS = [
    re.compile(r"\bS/?N[:\s]*([A-Z0-9\-]{4,})\b", re.I),
    re.compile(r"\bserial(?: number)?[:\s]*([A-Z0-9\-]{4,})\b", re.I),
    re.compile(r"\bimei[:\s]*([0-9]{8,15})\b", re.I),
    re.compile(r"\bservice[ -]?tag[:\s]*([A-Z0-9\-]{4,})\b", re.I),
]


def is_payment_context(metadata: Dict[str, Any] | None) -> bool:
    if not metadata:
        return False
    # metadata may include conversation state, intent, route
    state = metadata.get("conversation_state") or metadata.get("state") or ""
    intent = metadata.get("intent") or ""
    if isinstance(state, str) and state.lower() in ("checkout", "payment", "billing"):
        return True
    if isinstance(intent, str) and intent.lower() in ("checkout", "pay", "payment"):
        return True
    # Route-based hints
    route = metadata.get("route") or metadata.get("endpoint") or ""
    if isinstance(route, str) and "/payments" in route:
        return True
    return False


def extract_typed_entities(text: str) -> List[Dict[str, Any]]:
    """Return list of typed entities found in text (SERIAL_NUMBER, IMEI, etc.)."""
    found: List[Dict[str, Any]] = []
    if not text:
        return found
    for p in SERIAL_PATTERNS:
        for m in p.finditer(text):
            val = m.group(1)
            found.append({"type": "SERIAL_NUMBER", "value": val, "match": m.group(0)})
    # numeric-only long sequences (could be IMEI/PAN — leave to card_likeness to decide)
    for m in re.finditer(r"\b[0-9\-\s]{8,20}\b", text):
        candidate = re.sub(r"[^0-9]", "", m.group(0))
        if candidate and len(candidate) >= 8 and len(candidate) <= 20:
            found.append({"type": "NUMERIC_SEQ", "value": candidate, "match": m.group(0)})
    return found


def _hash_value(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def sanitize_serials(text: str, mode: str = "hash") -> Tuple[str, List[Dict[str, Any]]]:
    """Mask or hash serial-looking entities in the input text.

    mode: 'allow'|'hash'|'redact'
    Returns (sanitized_text, actions)
    """
    if not text:
        return text, []
    actions: List[Dict[str, Any]] = []
    out = text
    entities = extract_typed_entities(text)
    for ent in entities:
        v = ent.get("value") or ""
        if not v:
            continue
        if mode == "allow":
            actions.append({"action": "allow", "reason": "serial_allowed", "value_hash": _hash_value(v)})
            continue
        if mode == "redact":
            redacted = "[REDACTED_SERIAL]"
            out = out.replace(ent.get("match"), redacted)
            actions.append({"action": "redact", "reason": "serial_redacted", "redacted_text": redacted, "preserved_hash": _hash_value(v)})
        else:
            # default: hash
            hashed = _hash_value(v)
            out = out.replace(ent.get("match"), hashed)
            actions.append({"action": "hash", "reason": "serial_hashed", "preserved_hash": hashed})
    return out, actions


def apply_guardrails(message: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Apply tier-0 guardrails to a payload. Returns dict with sanitized_payload and guardrail_actions.

    message is expected to be a dict containing user-provided fields like 'query', 'text', 'input', 'images'.
    """
    settings_path = get_settings().feature_flags_path if hasattr(get_settings(), "feature_flags_path") else None
    try:
        flags = load_feature_flags(settings_path) if settings_path else {}
    except Exception:
        flags = {}

    handling = flags.get("DECISION_SERIAL_HANDLING", "hash")
    strict_gate = bool(flags.get("STRICT_PAYMENT_GATING", True))

    sanitized = dict(message)
    guardrail_actions: List[Dict[str, Any]] = []

    # Inspect relevant text fields
    text_fields = [k for k in ("text", "query", "input", "comment") if k in message]
    combined = " ".join([str(message.get(k) or "") for k in text_fields])

    # Extract typed entities (serials, numeric sequences)
    entities = extract_typed_entities(combined)
    if entities:
        # apply serial handling
        sanitized_text, actions = sanitize_serials(combined, mode=handling)
        # replace primary field if present
        if text_fields:
            sanitized[text_fields[0]] = sanitized_text
        guardrail_actions.extend(actions)

    # Card-likeness check on numeric candidates
    # check any numeric seqs found or raw combined
    suspect_card, details = is_card_like(combined)
    if suspect_card:
        guardrail_actions.append({"action": "suspect_card", "reason": "card_like_detected", "details": details})
        # if payment context and strict gating, mark block intent (decision made by policy gate later)
        if is_payment_context(metadata) and strict_gate:
            guardrail_actions.append({"action": "block_candidate", "reason": "payment_context_luhn_or_keyword", "details": details})

    return {"sanitized_payload": sanitized, "guardrail_actions": guardrail_actions, "flags": {"DECISION_SERIAL_HANDLING": handling, "STRICT_PAYMENT_GATING": strict_gate}}


def guardrail_profile_for_user(user_id: str | None, client_ip: str | None) -> Dict[str, Any]:
    """Return a lightweight guardrail profile for UI rendering and client-side checks.

    The profile is intentionally minimal and driven by feature flags so tests and
    pages can use it safely without importing heavier services.
    """
    settings_path = get_settings().feature_flags_path if hasattr(get_settings(), "feature_flags_path") else None
    try:
        flags = load_feature_flags(settings_path) if settings_path else {}
    except Exception:
        flags = {}

    profile = {
        "strict": bool(flags.get("STRICT_PAYMENT_GATING", True)),
        "max_len": int(flags.get("GUARDRAILS_MAX_LEN", 300)),
        "moderate": bool(flags.get("GUARDRAILS_MODERATE", True)),
    }

    # Simple user-tier hinting for local demo: treat user_id containing 'vip' as less strict
    if user_id and isinstance(user_id, str) and "vip" in user_id.lower():
        profile["strict"] = False
        profile["tier"] = "vip"

    return profile
