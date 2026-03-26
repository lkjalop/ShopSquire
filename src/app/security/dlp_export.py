"""CRIT-06 — Data Loss Prevention: secrets and PII scrubbing.

Two separate scrub passes:
1. ``dlp_scrub_text``     — credential / secret patterns (original behaviour).
2. ``dlp_scrub_pii``      — PII patterns (GDPR Art 5(1)(c), APP 11.1).
   Must be called before any text leaves the service boundary toward an
   external LLM provider, log sink, or export endpoint.

Add new patterns here; every pattern must have a test in
``tests/unit/test_dlp_export.py``.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Credential / secret patterns  (original)
# ---------------------------------------------------------------------------
_SECRET_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?i)-----BEGIN (?:RSA|EC|OPENSSH|DSA)? ?PRIVATE KEY-----"),
    re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:xoxb|xoxp|xoxe|xoxa)-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"(?i)\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
    re.compile(r"(?i)\b(?:sk|rk|pk)_(?:live|test)?_[A-Za-z0-9]{16,}\b"),
]

# ---------------------------------------------------------------------------
# PII patterns (CRIT-06 addition)
# Each tuple is (compiled_pattern, replacement_tag).
# Ordered from most-specific to least-specific to minimise false-positive
# over-redaction — e.g. credit cards before generic digit runs.
# ---------------------------------------------------------------------------
_PII_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # --- Apply most-specific / highest-priority patterns FIRST ---

    # Email addresses (before generic digit runs)
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    # Full name heuristic — Title + two capitalised words (before generic words)
    (re.compile(r"\b(?:Mr|Ms|Mrs|Miss|Dr|Prof|Rev)\.?\s+[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,30}\b"), "[NAME]"),
    # Australian mobile / landline (+61 or 0 + area 2–9 + 8 digits = 10 digits total)
    # Must come BEFORE TFN/Medicare digit patterns to avoid false matches on phone numbers.
    (re.compile(r"\b(?:\+61\s?|0)[2-9]\d{8}\b"), "[PHONE]"),
    # International phone (E.164-ish, e.g. +1-800-123-4567)
    (re.compile(r"\+[1-9]\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{4}\b"), "[PHONE]"),
    # Credit/debit card numbers (13–19 digits, optional spaces/dashes between groups)
    # Only match when surrounded by word boundaries to avoid over-matching order IDs.
    (re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)"), "[PAN]"),
    # Australian Tax File Number: first digit 1–9, two groups of 3 (xxx xxx xxx)
    # Must NOT start with 0 (avoids matching phone prefixes already replaced above).
    (re.compile(r"\b[1-9]\d{2}[ \-]\d{3}[ \-]\d{3}\b"), "[TFN]"),
    # Australian Medicare number: starts with 2–6, 10–11 digits (xxxx xxxxx x)
    (re.compile(r"\b[2-6]\d{3}[ \-]?\d{5}[ \-]?\d{1,2}\b"), "[MEDICARE]"),
    # Date of birth patterns (dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd)
    (re.compile(r"\b(?:\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{2}[/\-]\d{2})\b"), "[DOB]"),
    # IP addresses (v4) — can be PII under GDPR recital 30
    (re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"), "[IP]"),
    # Australian street addresses (heuristic)
    (re.compile(
        r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
        r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|Court|Ct|Lane|Ln|Way|Circuit|Cct|Close|Cl|Boulevard|Blvd)"
        r"(?:,\s+[A-Z][a-zA-Z\s]+)?\b"
    ), "[ADDRESS]"),
]


def _non_local_env() -> bool:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env not in ("local", "dev", "development", "test", "testing")


def dlp_scrub_text(value: str) -> Tuple[str, int]:
    """Scrub credential / secret patterns from *value*.

    Returns (scrubbed_text, hit_count).
    """
    text = str(value or "")
    hits = 0
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.search(out):
            hits += 1
            out = pat.sub("[REDACTED_SECRET]", out)
    return out, hits


def dlp_scrub_pii(value: str) -> Tuple[str, int]:
    """Scrub PII patterns from *value* before sending to an external system.

    Must be called on every prompt, log line, or export that crosses the
    service boundary toward an external LLM provider, log aggregator, or
    third-party API.

    Returns (scrubbed_text, hit_count).
    """
    text = str(value or "")
    hits = 0
    out = text
    for pat, replacement in _PII_PATTERNS:
        new = pat.sub(replacement, out)
        if new != out:
            hits += 1
        out = new
    return out, hits


def dlp_scrub_all(value: str) -> Tuple[str, int]:
    """Combined pass: scrub secrets then PII.  Returns (scrubbed, total_hits)."""
    scrubbed, h1 = dlp_scrub_text(value)
    scrubbed, h2 = dlp_scrub_pii(scrubbed)
    return scrubbed, h1 + h2


def dlp_sanitize_export_value(value: Any) -> Tuple[Any, int]:
    if isinstance(value, str):
        return dlp_scrub_text(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        total = 0
        for k, v in value.items():
            sv, h = dlp_sanitize_export_value(v)
            out[k] = sv
            total += h
        return out, total
    if isinstance(value, list):
        out = []
        total = 0
        for item in value:
            sv, h = dlp_sanitize_export_value(item)
            out.append(sv)
            total += h
        return out, total
    return value, 0


def dlp_sanitize_export_record(record: Dict[str, Any]) -> Dict[str, Any]:
    sanitized, hits = dlp_sanitize_export_value(record)
    if not isinstance(sanitized, dict):
        sanitized = {"value": sanitized}
    if hits > 0 and str(os.getenv("EXPORT_DLP_BLOCK_ON_SECRET", "1" if _non_local_env() else "0")).lower() in ("1", "true", "yes"):
        # Keep row shape stable while preventing leak.
        return {k: "[DLP_BLOCKED]" for k in sanitized.keys()}
    return sanitized
