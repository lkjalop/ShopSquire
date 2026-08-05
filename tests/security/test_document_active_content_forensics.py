from __future__ import annotations

import base64
import io
import zipfile

from src.app.security.email_attachment_intel import _forensics_from_attachments
from src.app.security.email_attachment_parser import hydrate_attachments_from_bytes


def _hydrate(name: str, content_type: str, blob: bytes):
    email = hydrate_attachments_from_bytes({"attachments": [{
        "name": name,
        "content_type": content_type,
        "content_b64": base64.b64encode(blob).decode("ascii"),
    }]})
    return email["attachments"][0]


def test_pdf_actions_and_embedded_content_are_explicit_findings():
    blob = b"%PDF-1.7\n/Catalog /OpenAction << /S /JavaScript /JS (marker) >> /Launch /URI /GoToR /EmbeddedFile\n%%EOF"
    attachment = _hydrate("supplier.pdf", "application/pdf", blob)
    assert attachment["pdf_actions"]["javascript"] >= 1
    assert attachment["pdf_actions"]["open_action"] == 1
    assert attachment["pdf_actions"]["launch"] == 1
    indicators, _ = _forensics_from_attachments([attachment])
    assert "pdf_active_content" in {item["type"] for item in indicators}


def test_office_external_relationship_and_macro_are_detected_without_fetching():
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as package:
        package.writestr("word/document.xml", "<w:document xmlns:w='urn:test'><w:t>Quote</w:t></w:document>")
        package.writestr(
            "word/_rels/document.xml.rels",
            "<Relationships><Relationship TargetMode='External' Target='https://192.0.2.10/template' Type='attachedTemplate'/></Relationships>",
        )
        package.writestr("word/vbaProject.bin", b"Sub Auto_Open()")
    attachment = _hydrate("supplier.docm", "application/vnd.ms-word.document.macroEnabled.12", blob.getvalue())
    assert len(attachment["office_external_relationships"]) == 1
    assert attachment["office_macro_member_count"] == 1
    indicators, _ = _forensics_from_attachments([attachment])
    assert {"office_external_relationship", "office_macro_content"} <= {item["type"] for item in indicators}
