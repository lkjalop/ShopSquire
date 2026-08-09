from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from src.app.main import create_app


def _pdf_with_text(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode() + payload + b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(body)


def test_plain_text_requirements_use_the_same_read_only_evidence_boundary(monkeypatch):
    import src.app.routers.vision as vision

    monkeypatch.setattr(vision, "_persist_artifact_verdict", lambda **kwargs: {
        "artifact_id": kwargs["artifact_id"], "sha256": kwargs["sha256"],
        "verdict_version": 1, "state": kwargs["state"], "authority": "read_only",
    })
    content = (
        b"RAM 32GB minimum\nStorage 1TB NVMe\n"
        b"Windows 11 Pro recommended\nGPU VRAM 16GB acceptable alternative"
    )
    response = TestClient(create_app()).post(
        "/api/v1/vision/triage?extract_text=1",
        headers={"x-api-key": "local-merchant-key"},
        files={"image": ("requirements.txt", content, "text/plain")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["extracted_text"] == content.decode("utf-8")
    assert payload["artifact"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert payload["artifact"]["state"] == "clean"
    assert payload["artifact"]["authority"] == "read_only"
    assert payload["security"]["commercial_authority"] == "read_only"


def test_binary_content_disguised_as_text_is_rejected():
    response = TestClient(create_app()).post(
        "/api/v1/vision/triage?extract_text=1",
        headers={"x-api-key": "local-merchant-key"},
        files={"image": ("requirements.txt", b"RAM 32GB\x00\x00binary", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "document_conversion_failed"


def test_pdf_requirements_use_the_same_read_only_evidence_boundary(monkeypatch):
    import src.app.routers.vision as vision

    monkeypatch.setattr(vision, "_persist_artifact_verdict", lambda **kwargs: {
        "artifact_id": kwargs["artifact_id"], "sha256": kwargs["sha256"],
        "verdict_version": 1, "state": kwargs["state"], "authority": "read_only",
    })
    content = _pdf_with_text(
        "RAM 32GB minimum Storage 1TB NVMe Windows 11 Pro recommended",
    )
    response = TestClient(create_app()).post(
        "/api/v1/vision/triage?extract_text=1",
        headers={"x-api-key": "local-merchant-key"},
        files={"image": ("requirements.pdf", content, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "RAM 32GB minimum" in payload["extracted_text"]
    assert payload["artifact"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert payload["artifact"]["authority"] == "read_only"
    assert payload["security"]["commercial_authority"] == "read_only"
