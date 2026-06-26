"""Gmail ingestion job — the read-only fetch seam for the email poller + Supplier_Inbox_Reader.

There is no live Gmail connector wired yet (OAuth/token + Gmail API are part of Phase-8 production
transports). Until then, fetch_recent_emails returns [] when no connector is configured — an EXPLICIT
no-op instead of an ImportError the poller has to treat as control flow. When a connector is added,
this is the single place real messages enter; each message is the canonical envelope the poller +
email-security pipeline expect:  {id, sender, sender_domain, subject, body, received_at}.

Read-only; never sends; never raises (returns [] on any failure).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _connector_configured() -> bool:
    return bool(os.getenv("GMAIL_CONNECTOR_TOKEN") or os.getenv("GMAIL_OAUTH_TOKEN"))


def fetch_recent_emails(*, batch_size: int = 25) -> List[Dict[str, Any]]:
    """Return up to ``batch_size`` recent inbound messages. [] when no Gmail connector is configured
    (the default today) — the explicit seam where a real Gmail fetch will land (Phase-8)."""
    if not _connector_configured():
        logger.debug("ingest_gmail.fetch_recent_emails: no Gmail connector configured → no messages")
        return []
    try:
        # Real Gmail API fetch goes here (deferred — Phase-8 production transports). Until then,
        # a configured-but-unimplemented connector still returns an empty, honest result.
        logger.info("ingest_gmail.fetch_recent_emails: connector configured but live fetch not implemented")
        return []
    except Exception as exc:  # never let a fetch error crash the poll loop
        logger.warning("ingest_gmail.fetch_recent_emails failed: %s", exc)
        return []
