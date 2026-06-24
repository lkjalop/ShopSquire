#!/usr/bin/env python3
"""PCI DSS no-PAN repository scan (Req. 3 — do NOT store cardholder data).

Walks the repository for Luhn-valid card-number-like digit runs (13-19 digits, major-network BIN
prefix) and FAILS CI if any are found outside the documented test-PAN allowlist. This catches a real
PAN accidentally committed to source, config, or a checked-in log — while permitting the standard
network TEST PANs (which are NOT real cardholder data).

Usage:
    python scripts/scan_no_pan.py [repo_root]   # exit 0 = clean, 1 = candidate PAN(s) found

Note: ShopSquire tokenizes payments and stores no CHD; this is the defence-in-depth guard that keeps
it that way. We claim "tokenized, no CHD stored" — never "PCI compliant" (that needs a QSA).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

# Standard network TEST PANs (Stripe/Adyen/Braintree docs) — NOT real cardholder data, so permitted.
_ALLOWLISTED_TEST_PANS = {
    "4242424242424242", "4111111111111111", "4012888888881881", "4000056655665556",
    "5555555555554444", "5200828282828210", "5105105105105100", "2223003122003222",
    "378282246310005", "371449635398431", "6011111111111117", "6011000990139424",
    "3056930009020004", "3566002020360505", "30569309025904", "38520000023237",
    "4000000000000002", "4000000000009995", "4000002500003155", "4000000000003220",
}

# Candidate PANs: a contiguous 13-19 digit run, OR the standard printed groupings (4-4-4-4 for
# 16-digit networks, 4-6-5 for Amex). Requiring contiguous-or-grouped-in-4s avoids the SVG-path /
# coordinate / version-string false positives that arise from allowing arbitrary single-space gaps.
_CANDIDATE_RE = re.compile(
    r"(?<![0-9])("
    r"[0-9]{13,19}"                        # contiguous 13-19 digits
    r"|[0-9]{4}(?:[ -][0-9]{4}){3}"        # 4-4-4-4  (16 digits: Visa/MC/Discover)
    r"|[0-9]{4}[ -][0-9]{6}[ -][0-9]{5}"   # 4-6-5    (15 digits: Amex)
    r")(?![0-9])"
)

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages", ".idea", ".vscode",
    "coverage", "htmlcov", ".next", ".turbo",
}
_SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".pdf",
    ".zip", ".gz", ".tar", ".tgz", ".woff", ".woff2", ".ttf", ".eot", ".map", ".lock",
    ".node", ".exe", ".dll", ".so", ".dylib", ".bin", ".onnx", ".pt", ".pack", ".wasm",
    # binary data/DB files — not human-readable source/config/log; reading as text yields random
    # byte runs that false-positive as PANs. (Scanning a live DB for CHD is a separate control.)
    ".sqlite", ".sqlite3", ".db", ".db3", ".mdb", ".parquet", ".feather", ".arrow",
    ".h5", ".hdf5", ".npy", ".npz", ".pkl", ".pickle", ".joblib", ".model", ".pb",
}


def _luhn_ok(num: str) -> bool:
    """Standard Luhn checksum — the structural property every real PAN satisfies."""
    digits = [int(c) for c in num]
    odd = digits[-1::-2]
    even = digits[-2::-2]
    total = sum(odd) + sum(sum(divmod(d * 2, 10)) for d in even)
    return total % 10 == 0


def find_pans_in_text(text: str) -> List[str]:
    """Return normalized (digits-only) candidate PANs in ``text`` — major-network BIN, Luhn-valid,
    not an allowlisted test PAN. Empty list = clean."""
    hits: List[str] = []
    for m in _CANDIDATE_RE.finditer(text):
        raw = re.sub(r"[ -]", "", m.group(0))
        if not (13 <= len(raw) <= 19):
            continue
        if raw[0] not in "3456":  # Amex/Diners/JCB(3), Visa(4), Mastercard(5), Discover(6)
            continue
        if raw in _ALLOWLISTED_TEST_PANS:
            continue
        if not _luhn_ok(raw):
            continue
        hits.append(raw)
    return hits


def scan_repo(root: Path, skip_files: Iterable[Path] = ()) -> List[Tuple[str, int, str]]:
    """Scan every text file under ``root``; return (relpath, line_no, masked_pan) findings.

    Uses os.walk with in-place dir pruning so vendor trees (node_modules, .git, venvs) are never
    descended into — orders of magnitude faster than walking then filtering."""
    skip_abs = {p.resolve() for p in skip_files}
    findings: List[Tuple[str, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]  # prune before descending
        for fname in filenames:
            path = Path(dirpath) / fname
            if path.suffix.lower() in _SKIP_SUFFIXES:
                continue
            if path.resolve() in skip_abs:
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:8192]:
                continue  # binary file (null bytes) — not human-readable source/config/log
            text = raw.decode("utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                for pan in find_pans_in_text(line):
                    findings.append((str(path.relative_to(root)), i, pan[:6] + "…" + pan[-4:]))
    return findings


def main(argv: List[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    # The scanner and its test legitimately contain PAN-shaped strings (allowlist + planted fixtures).
    self_files = [Path(__file__).resolve(), root / "tests" / "security" / "test_no_pan_scan.py"]
    findings = scan_repo(root, skip_files=self_files)
    if findings:
        print(f"PCI no-PAN scan FAILED — {len(findings)} candidate PAN(s) found:")
        for f, ln, masked in findings:
            print(f"  {f}:{ln}: {masked}")
        print(
            "Remove cardholder data from the repo (PCI DSS Req. 3). If this is a documented network "
            "TEST PAN, add it to _ALLOWLISTED_TEST_PANS in scripts/scan_no_pan.py."
        )
        return 1
    print("PCI no-PAN scan PASSED — no cardholder data detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
