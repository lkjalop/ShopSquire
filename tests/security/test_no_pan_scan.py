"""PCI #4 — no-PAN repository scan (PCI DSS Req. 3: do not store cardholder data).

Verifies the scanner detects a real (Luhn-valid, major-network) PAN, ignores the documented network
TEST PANs, ignores non-PAN digit runs, and reports clean on a repo with none. The scanner itself and
this test are excluded from the live repo scan (they legitimately contain PAN-shaped strings).
"""
from __future__ import annotations

from scripts.scan_no_pan import _luhn_ok, find_pans_in_text, scan_repo


def _luhn_complete(prefix: str) -> str:
    for d in "0123456789":
        if _luhn_ok(prefix + d):
            return prefix + d
    raise AssertionError("unreachable")


def test_detects_real_luhn_valid_pan():
    fake = _luhn_complete("400012345678901")  # 16-digit Visa-shaped, not an allowlisted test card
    assert find_pans_in_text(f'stored_card = "{fake}"') == [fake]
    # tolerate spaced/dashed formatting
    spaced = " ".join([fake[i:i + 4] for i in range(0, 16, 4)])
    assert fake in find_pans_in_text(f"card: {spaced}")


def test_ignores_documented_test_pans():
    for pan in ("4242424242424242", "4111111111111111", "5555555555554444", "378282246310005"):
        assert find_pans_in_text(pan) == []


def test_ignores_non_pan_digit_runs():
    assert find_pans_in_text("1234567890123456") == []        # 16 digits, fails Luhn
    assert find_pans_in_text("order id 9900112233445") == []  # 13 digits, fails Luhn
    assert find_pans_in_text("2026-06-24T12:00:00 trace=000111222") == []
    assert find_pans_in_text("phone +1 415 555 0100") == []


def test_scan_repo_clean_and_dirty(tmp_path):
    (tmp_path / "ok.py").write_text("x = 'hello world'\nattempts = 600000\n", encoding="utf-8")
    assert scan_repo(tmp_path) == []
    fake = _luhn_complete("400012345678901")
    (tmp_path / "leak.log").write_text(f"charge succeeded for {fake}\n", encoding="utf-8")
    findings = scan_repo(tmp_path)
    assert len(findings) == 1
    relpath, line_no, masked = findings[0]
    assert relpath == "leak.log" and line_no == 1
    assert masked.startswith("400012") and masked.endswith("9017") and "…" in masked


def test_scan_repo_skips_binary_and_vendor_dirs(tmp_path):
    fake = _luhn_complete("400012345678901")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "vendor.js").write_text(fake, encoding="utf-8")
    (tmp_path / "image.png").write_text(fake, encoding="utf-8")  # skipped by suffix
    assert scan_repo(tmp_path) == []
