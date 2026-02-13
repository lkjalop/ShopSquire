import base64

from src.app.security.email_attachment_parser import hydrate_attachments_from_bytes
from src.app.security.email_attachment_intel import analyze_email_artifacts


def test_pdf_forensics_fields_present_and_bank_fingerprint_extracted():
    # Minimal "pdf-ish" bytes: include embedded file markers + ObjStm markers and bank fields in text.
    pdf_bytes = b"%PDF-1.7\n/EmbeddedFile /Filespec /ObjStm /ObjStm /ObjStm\nBSB: 062-205\nAccount No.: 1049 3827\n"
    email = {
        "subject": "Invoice",
        "body": "See attachment",
        "vendor_domain": "ingramfake.com.au",
        "bank_fingerprint": "",  # baseline not used in this test
        "attachments": [
            {
                "name": "invoice.pdf",
                "content_type": "application/pdf",
                "content_b64": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        ],
    }
    hydrated = hydrate_attachments_from_bytes(email)
    a = (hydrated.get("attachments") or [])[0]
    assert int(a.get("embedded_files_count") or 0) >= 1
    assert int(a.get("pdf_objstm_count") or 0) >= 3
    assert isinstance(a.get("bank_fields"), dict)
    assert a.get("extracted_bank_fingerprint")

    intel = analyze_email_artifacts(hydrated)
    ind_types = {i.get("type") for i in (intel.get("indicators") or [])}
    assert "pdf_embedded_files" in ind_types
    assert "pdf_object_stream_heavy" in ind_types
    assert "bank_fields_present_in_attachment" in ind_types

