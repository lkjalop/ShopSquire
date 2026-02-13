import base64
import io
import os
import zipfile

from fastapi.testclient import TestClient

from src.app.main import create_app


def _docx_like_b64(text: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>""",
        )
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_email_security_evaluate_accepts_binary_attachment_bytes():
    os.environ["DEVELOPER_API_KEY"] = "local-developer-key"
    app = create_app()
    client = TestClient(app)

    doc_text = "ABN: 13 504 561 230 Invoice No: INV-2026-00847 Due Date: 27 February 2026 Total Amount Due: $47,272.50"
    payload = {
        "tenant_id": "t-binary",
        "message_id": "m-binary-1",
        "from_addr": "accounts@supplier.example",
        "reply_to": "accounts@supplier.example",
        "subject": "Invoice attached",
        "body": "Please review attached invoice",
        "attachments": [
            {
                "name": "invoice.docx",
                "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "content_b64": _docx_like_b64(doc_text),
            }
        ],
    }
    r = client.post("/api/v1/email_security/evaluate", json=payload, headers={"x-api-key": "local-developer-key"})
    assert r.status_code == 200
    out = r.json()
    artifact = ((out.get("evidence_snapshot") or {}).get("artifact_intel") or {})
    parsed = artifact.get("parsed_fields") or {}
    assert parsed.get("abn") == "13504561230"
    assert parsed.get("invoice_number")
    iocs = out.get("iocs") or []
    assert any(str(x.get("type")) == "hash" for x in iocs)

