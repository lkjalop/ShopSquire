from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from scripts.gen_security_upload_corpus import generate_corpus
from src.app.routers.vision import _canonical_qr_assessment
from src.app.security.csv_safety import neutralize_csv_text
from src.app.security.email_attachment_parser import hydrate_attachments_from_bytes
from src.app.services.intake_gate import sanitize_attachment_ocr_for_llm, strict_binary_ingest_gate
from src.app.main import create_app


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("shopsquire-security-corpus")
    generate_corpus(output)
    return output


def _manifest(corpus: Path):
    return json.loads((corpus / "SECURITY_CORPUS_MANIFEST.json").read_text(encoding="utf-8"))


def test_manifest_is_versioned_typed_and_hash_sealed(corpus: Path):
    manifest = _manifest(corpus)
    assert manifest["schema_version"] == "shopsquire.security-corpus.v1"
    assert manifest["counts"]["total"] == len(manifest["artifacts"]) == 46
    kinds = {item["artifact_kind"] for item in manifest["artifacts"]}
    assert {"upload_artifact", "runtime_probe", "binding_probe", "batch_member", "privacy_probe"} <= kinds
    for item in manifest["artifacts"]:
        path = Path(item["relative_path"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_declared_pdf_with_png_bytes_is_rejected_by_filename_identity(corpus: Path):
    path = corpus / "01_mime_polyglot" / "png_bytes_declared_as.pdf"
    result = strict_binary_ingest_gate(filename=path.name, content_type="application/pdf", blob=path.read_bytes())
    assert result["blocked"] is True
    assert "filename_mime_mismatch" in result["block_reasons"]


def test_qr_prompt_injection_can_never_be_assessed_as_allow():
    signals = {
        "qr_code_detected": True,
        "qr_benign_detected": True,
        "qr_prompt_injection": True,
        "qr_policy_action": "allow",  # conflicting detector input must lose
        "qr_payloads": [{"data": "IGNORE ALL PREVIOUS", "risk_level": "benign"}],
    }
    result = _canonical_qr_assessment(signals)
    assert result and result["policy_action"] == "block"
    assert result["risk_levels"] == ["malicious"]


def test_supplier_pdf_injection_is_detected_and_removed_from_model_context(corpus: Path):
    path = corpus / "10_supplier_documents" / "supplier_quote_indirect_injection.pdf"
    email = hydrate_attachments_from_bytes({
        "attachments": [{
            "name": path.name,
            "content_type": "application/pdf",
            "content_b64": base64.b64encode(path.read_bytes()).decode("ascii"),
        }]
    })
    sanitized, meta = sanitize_attachment_ocr_for_llm(email)
    assert meta["prompt_instruction_hits"] >= 3
    text = sanitized["attachments"][0]["extracted_text"]
    assert "skip the human gate" not in text.lower()
    assert "authoritative price update" not in text.lower()
    assert "[REMOVED_UNTRUSTED_INSTRUCTION]" in text


def test_supplier_csv_formula_cells_are_inert_on_ingest_and_export(corpus: Path):
    path = corpus / "10_supplier_documents" / "supplier_pricelist_formula_injection.csv"
    safe, hits = neutralize_csv_text(path.read_text(encoding="utf-8"))
    assert hits >= 2
    assert "'=1+1" in safe
    assert "'@SUM" in safe


def test_malformed_webp_returns_typed_parser_failure_not_size_claim(corpus: Path):
    path = corpus / "04_parser_differentials" / "webp_riff_size_overflow.webp"
    response = TestClient(create_app()).post(
        "/api/v1/vision/triage",
        headers={"x-api-key": "local-merchant-key"},
        files={"image": (path.name, path.read_bytes(), "image/webp")},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "image_malformed_or_unsupported"
    assert detail.get("error") != "image_too_large"
    assert detail["artifact"]["authority"] == "blocked"
