import base64

from src.app.security import email_attachment_parser as mod


def test_pdf_hydration_uses_ocr_fallback_for_semantic_bank_fields(monkeypatch):
    monkeypatch.setattr(mod, "_extract_pdf_text_basic", lambda blob: "Invoice", raising=True)
    monkeypatch.setattr(
        mod,
        "_ocr_pdf_pages",
        lambda blob, max_pages=3, scale=2.0: "Updated payment details\nBSB: 032-089\nAccount No: 582947-001\nAccount Name: Ingram Logistics Holdings",
        raising=True,
    )

    email = {
        "attachments": [
            {
                "name": "invoice.pdf",
                "content_type": "application/pdf",
                "content_b64": base64.b64encode(b"%PDF-1.7 fake").decode("ascii"),
            }
        ]
    }

    out = mod.hydrate_attachments_from_bytes(email)
    att = (out.get("attachments") or [])[0]
    assert "Updated payment details" in str(att.get("extracted_text") or "")
    assert isinstance(att.get("bank_fields"), dict)
    assert att["bank_fields"].get("bsb") == "032-089"
    assert att["bank_fields"].get("account_number") == "582947-001"
    assert att.get("extracted_account_name") == "Ingram Logistics Holdings"


def test_pdf_hydration_extracts_embedded_urls_when_text_is_sparse():
    blob = b"%PDF-1.7\n/URI(https://payments.example/verify)\n"
    email = {
        "attachments": [
            {
                "name": "invoice.pdf",
                "content_type": "application/pdf",
                "content_b64": base64.b64encode(blob).decode("ascii"),
            }
        ]
    }
    out = mod.hydrate_attachments_from_bytes(email)
    att = (out.get("attachments") or [])[0]
    assert "https://payments.example/verify" in list(att.get("pdf_embedded_urls") or [])
    assert "https://payments.example/verify" in str(att.get("extracted_text") or "")


def test_pdf_text_looks_unusable_for_reportlab_object_noise():
    noisy = "PDF-1.4 ReportLab Generated PDF document opensource 1 0 obj /Type /Font endobj 2 0 obj /Catalog stream endstream xref"
    assert mod._pdf_text_looks_unusable(noisy) is True
