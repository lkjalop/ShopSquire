"""Email thread-depth analysis for reply-chain hijack detection.

Parses RFC-2822 ``References`` / ``In-Reply-To`` headers to build a
thread graph and detect anomalies that indicate thread-insertion or
hijack attacks common in BEC campaigns.

Signals emitted
----------------
- ``thread_depth_anomaly``      – Thread depth exceeds baseline for sender.
- ``thread_insertion_suspected`` – Message-ID gap or foreign message-ID
  inserted into an otherwise consistent chain.
- ``thread_age_gap``            – Time gap between previous message and
  this one is unusually large (stale thread revival).
- ``references_header_forged``  – References header present but
  In-Reply-To does not match the last reference.

ENV configuration
-----------------
THREAD_MAX_EXPECTED_DEPTH        – Depth beyond which we flag (default 15)
THREAD_AGE_GAP_HOURS             – Hours gap that triggers stale flag (default 168 = 7 days)
THREAD_INSERTION_DOMAIN_CHECK    – "1" to flag cross-domain message-IDs (default "1")
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shopsquire.thread_depth")


def _env_int(key: str, default: int) -> int:
    try:
        v = os.getenv(key)
        if v is None or str(v).strip() == "":
            return default
        return max(1, int(float(str(v).strip())))
    except Exception:
        return default


def _parse_message_ids(header_value: str | None) -> List[str]:
    """Extract ``<message-id>`` tokens from a References or In-Reply-To header."""
    if not header_value:
        return []
    return re.findall(r"<([^>]+)>", str(header_value))


def _extract_domain(message_id: str) -> str | None:
    """Return the domain portion of a message-id (text after '@')."""
    if "@" in message_id:
        return message_id.rsplit("@", 1)[-1].strip().lower()
    return None


def _hash_mid(mid: str) -> str:
    return hashlib.sha256(mid.encode("utf-8")).hexdigest()[:16]


def analyze_thread_depth(
    email: Dict[str, Any],
    *,
    sender_domain: str | None = None,
) -> Dict[str, Any]:
    """Analyse an email's thread headers and return depth + anomaly signals.

    Parameters
    ----------
    email : dict
        Expected keys (all optional):
        - ``references`` – value of the References header (space-separated message-IDs)
        - ``in_reply_to`` – value of the In-Reply-To header
        - ``message_id`` – this message's own Message-ID
        - ``date`` – ISO-8601 date string for this message
        - ``from_addr`` – sender address (used for domain extraction)
        - ``prior_date`` – ISO-8601 date of the previous message in thread (if known)
    sender_domain : str, optional
        Override for sender domain (otherwise extracted from ``from_addr``).

    Returns
    -------
    dict with keys:
        thread_depth, reference_ids, indicators (list of dicts), meta
    """
    max_depth = _env_int("THREAD_MAX_EXPECTED_DEPTH", 15)
    age_gap_hours = _env_int("THREAD_AGE_GAP_HOURS", 168)
    domain_check = os.getenv("THREAD_INSERTION_DOMAIN_CHECK", "1").strip() not in ("0", "false", "no")

    references_raw = str(email.get("references") or "")
    in_reply_to_raw = str(email.get("in_reply_to") or "")
    message_id = str(email.get("message_id") or "").strip().strip("<>")

    ref_ids = _parse_message_ids(references_raw)
    irt_ids = _parse_message_ids(in_reply_to_raw)

    thread_depth = len(ref_ids)  # depth = number of ancestors in References
    if not ref_ids and irt_ids:
        thread_depth = 1  # at least one parent

    indicators: List[Dict[str, Any]] = []

    # 1) Thread depth anomaly
    if thread_depth > max_depth:
        indicators.append({
            "type": "thread_depth_anomaly",
            "value": thread_depth,
            "reason": f"Thread depth {thread_depth} exceeds threshold {max_depth}",
        })

    # 2) References vs In-Reply-To consistency
    if ref_ids and irt_ids:
        last_ref = ref_ids[-1]
        if irt_ids[0] != last_ref:
            indicators.append({
                "type": "references_header_forged",
                "value": True,
                "reason": (
                    f"In-Reply-To ({_hash_mid(irt_ids[0])}) does not match "
                    f"last Reference ({_hash_mid(last_ref)})"
                ),
            })

    # 3) Cross-domain insertion detection
    if domain_check and ref_ids and sender_domain is None:
        from_addr = str(email.get("from_addr") or "")
        if "@" in from_addr:
            sender_domain = from_addr.rsplit("@", 1)[-1].strip().lower().rstrip(">")

    if domain_check and ref_ids:
        domains_in_chain = [_extract_domain(mid) for mid in ref_ids if _extract_domain(mid)]
        if sender_domain and domains_in_chain:
            # A consistent chain normally has at most 2 domains (sender + recipient).
            # If a third foreign domain appears in the middle, flag it.
            unique_domains = set(d for d in domains_in_chain if d)
            foreign = unique_domains - {sender_domain}
            # Allow one other domain (the conversation partner); flag if 3+
            if len(foreign) >= 2:
                indicators.append({
                    "type": "thread_insertion_suspected",
                    "value": sorted(foreign),
                    "reason": f"Multiple foreign domains in References chain: {sorted(foreign)}",
                })

    # 4) Stale thread revival (age gap)
    msg_date = _parse_datetime(email.get("date"))
    prior_date = _parse_datetime(email.get("prior_date"))
    if msg_date and prior_date:
        gap = msg_date - prior_date
        gap_hours = gap.total_seconds() / 3600.0
        if gap_hours > age_gap_hours:
            indicators.append({
                "type": "thread_age_gap",
                "value": round(gap_hours, 1),
                "reason": f"Thread revival after {round(gap_hours, 1)}h gap (threshold {age_gap_hours}h)",
            })

    return {
        "thread_depth": thread_depth,
        "reference_ids_count": len(ref_ids),
        "in_reply_to_count": len(irt_ids),
        "indicators": indicators,
        "meta": {
            "max_depth_threshold": max_depth,
            "age_gap_threshold_hours": age_gap_hours,
            "message_id_hash": _hash_mid(message_id) if message_id else None,
        },
    }


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        pass
    # email.utils.parsedate fallback
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(str(value))
    except Exception:
        return None
