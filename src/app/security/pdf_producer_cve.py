"""S-006 — PDF producer CVE/KEV check.

Flags old or known-vulnerable PDF producers (e.g. Excel 2010, LibreOffice < 7,
wkhtmltopdf, etc.) and optionally cross-references a local CVE/KEV catalogue.

The known-vulnerable list is intentionally conservative: entries come from
NIST NVD and CISA KEV advisories for PDF-rendering/generating components.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Known-vulnerable PDF producer patterns
# ---------------------------------------------------------------------------
# Each entry: (compiled regex, human label, severity, CVE IDs / notes)
_VULN_PRODUCERS: List[Tuple[re.Pattern[str], str, str, List[str]]] = [
    (
        re.compile(r"Microsoft.*Excel.*20(?:07|10)", re.IGNORECASE),
        "Microsoft Excel 2007/2010",
        "high",
        ["CVE-2017-11882", "CVE-2018-0802"],
    ),
    (
        re.compile(r"Microsoft.*Word.*20(?:07|10)", re.IGNORECASE),
        "Microsoft Word 2007/2010",
        "high",
        ["CVE-2017-11882", "CVE-2018-0802"],
    ),
    (
        re.compile(r"Microsoft.*Office.*20(?:07|10)", re.IGNORECASE),
        "Microsoft Office 2007/2010",
        "high",
        ["CVE-2017-11882"],
    ),
    (
        re.compile(r"LibreOffice\s+[1-6]\.", re.IGNORECASE),
        "LibreOffice < 7.0",
        "medium",
        ["CVE-2022-26305", "CVE-2022-26306"],
    ),
    (
        re.compile(r"wkhtmltopdf\s+0\.", re.IGNORECASE),
        "wkhtmltopdf 0.x (SSRF-prone)",
        "high",
        ["CVE-2022-35583"],
    ),
    (
        re.compile(r"PhantomJS", re.IGNORECASE),
        "PhantomJS (unmaintained)",
        "medium",
        [],
    ),
    (
        re.compile(r"Acrobat.*[4-9]\.", re.IGNORECASE),
        "Adobe Acrobat <= 9",
        "high",
        ["CVE-2009-0658", "CVE-2009-4324"],
    ),
    (
        re.compile(r"iText\s*[1-4]\.", re.IGNORECASE),
        "iText < 5 (legacy Java PDF lib)",
        "low",
        [],
    ),
    (
        re.compile(r"FPDF\s+1\.[0-6]", re.IGNORECASE),
        "FPDF <= 1.6",
        "low",
        [],
    ),
    (
        re.compile(r"PDF-XChange\s+[1-3]\.", re.IGNORECASE),
        "PDF-XChange < 4",
        "medium",
        [],
    ),
    (
        re.compile(r"OpenOffice", re.IGNORECASE),
        "OpenOffice (EOL / limited patching)",
        "medium",
        ["CVE-2021-33035"],
    ),
]

# Anomalous but not necessarily vulnerable — flag for review.
_ANOMALOUS_PRODUCERS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"cairo\s+\d", re.IGNORECASE), "cairo (unusual for invoices)"),
    (re.compile(r"Skia/PDF", re.IGNORECASE), "Skia/PDF (Chrome print-to-PDF)"),
    (re.compile(r"WeasyPrint", re.IGNORECASE), "WeasyPrint"),
]


def _load_kev_catalogue() -> Dict[str, Any]:
    """Load optional local KEV (Known Exploited Vulnerabilities) file.

    Expected format (`config/security/kev_catalogue.json`):
      { "CVE-YYYY-NNNNN": { "vendor": "...", "product": "...", "severity": "...", ... }, ... }
    """
    path = os.getenv("KEV_CATALOGUE_PATH", os.path.join("config", "security", "kev_catalogue.json"))
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def check_producer(producer: str | None, creator: str | None = None) -> Dict[str, Any]:
    """Check a PDF producer/creator string against known-vulnerable patterns.

    Returns:
        dict with keys: flagged (bool), severity, label, cves, anomalous, kev_matches
    """
    result: Dict[str, Any] = {
        "flagged": False,
        "severity": "info",
        "label": None,
        "producer": producer,
        "creator": creator,
        "cves": [],
        "anomalous": False,
        "anomalous_label": None,
        "kev_matches": [],
    }
    combined = " | ".join(filter(None, [str(producer or "").strip(), str(creator or "").strip()]))
    if not combined.strip():
        return result

    # Check vulnerable producers
    for pat, label, sev, cves in _VULN_PRODUCERS:
        if pat.search(combined):
            result["flagged"] = True
            result["severity"] = sev
            result["label"] = label
            result["cves"] = list(cves)
            break

    # Check anomalous producers (lower priority)
    for pat, label in _ANOMALOUS_PRODUCERS:
        if pat.search(combined):
            result["anomalous"] = True
            result["anomalous_label"] = label
            break

    # Cross-reference KEV catalogue for any listed CVEs
    if result["cves"]:
        kev = _load_kev_catalogue()
        if kev:
            for cve_id in result["cves"]:
                entry = kev.get(cve_id)
                if entry:
                    result["kev_matches"].append({"cve": cve_id, **entry})

    return result


def check_attachment_producers(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run producer checks on a list of parsed attachment dicts.

    Each attachment dict may have `pdf_producer` and `pdf_creator` keys
    (populated by email_attachment_parser.hydrate_attachments_from_bytes).
    """
    results: List[Dict[str, Any]] = []
    for att in attachments or []:
        producer = att.get("pdf_producer")
        creator = att.get("pdf_creator")
        if not producer and not creator:
            continue
        res = check_producer(producer, creator)
        res["attachment_name"] = att.get("name")
        results.append(res)
    return results
