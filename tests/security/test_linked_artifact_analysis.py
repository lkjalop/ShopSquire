from __future__ import annotations

from types import SimpleNamespace


def test_linked_artifact_analysis_detects_pdf_ssn_and_pii(monkeypatch):
    from src.app.security import linked_artifact_analysis as mod

    pdf_like = b"%PDF-1.7\n1 0 obj\n(SSN 123-45-6789)\nendobj\n"

    def _fake_safe_request(method: str, url: str, **_: object):
        return SimpleNamespace(
            status_code=200,
            url=url,
            headers={"content-type": "application/pdf", "content-disposition": 'attachment; filename="ssn-sheet.pdf"'},
            content=pdf_like,
        )

    monkeypatch.setattr(mod, "safe_request", _fake_safe_request)
    out = mod.analyze_linked_artifact(url="https://example.test/ssn-sheet.pdf")
    assert out["linked_artifact_available"] is True
    assert out["linked_artifact_type"] == "pdf"
    assert out["pii_detected"] is True
    assert "ssn" in out["pii_type"]
    assert "123-45-6789" in out["ssn_hits"]
    assert out["linked_attack_hypothesis"] == "linked_pii_exposure"


def test_linked_artifact_analysis_follows_landing_page_to_pdf(monkeypatch):
    from src.app.security import linked_artifact_analysis as mod

    landing_html = b'<html><head><title>scan</title></head><body><a href="/docs/ssn-sheet.pdf">Download PDF</a></body></html>'
    pdf_like = b"%PDF-1.7\n1 0 obj\n(SSN 123-45-6789)\nendobj\n"

    def _fake_safe_request(method: str, url: str, **_: object):
        if url == "https://example.test/landing":
            return SimpleNamespace(
                status_code=200,
                url=url,
                headers={"content-type": "text/html"},
                content=landing_html,
            )
        if url == "https://example.test/docs/ssn-sheet.pdf":
            return SimpleNamespace(
                status_code=200,
                url=url,
                headers={"content-type": "application/pdf", "content-disposition": 'attachment; filename="ssn-sheet.pdf"'},
                content=pdf_like,
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(mod, "safe_request", _fake_safe_request)
    out = mod.analyze_linked_artifact(url="https://example.test/landing")
    assert out["linked_artifact_available"] is True
    assert out["linked_artifact_type"] == "pdf"
    assert out["pii_detected"] is True
    assert "123-45-6789" in out["ssn_hits"]
    assert out["linked_final_url"] == "https://example.test/docs/ssn-sheet.pdf"
    assert out["linked_landing_page_url"] == "https://example.test/landing"


def test_linked_artifact_analysis_uses_pdf_ocr_when_text_extract_empty(monkeypatch):
    from src.app.security import linked_artifact_analysis as mod

    pdf_like = b"%PDF-1.7\n1 0 obj\n<< /Type /Page >>\nendobj\n"

    def _fake_safe_request(method: str, url: str, **_: object):
        return SimpleNamespace(
            status_code=200,
            url=url,
            headers={"content-type": "application/pdf", "content-disposition": 'attachment; filename="scan.pdf"'},
            content=pdf_like,
        )

    monkeypatch.setattr(mod, "safe_request", _fake_safe_request)
    monkeypatch.setattr(mod, "_extract_text", lambda *args, **kwargs: "")
    monkeypatch.setattr(mod, "_extract_pdf_text", lambda *args, **kwargs: "")
    monkeypatch.setattr(mod, "_ocr_pdf_text", lambda *args, **kwargs: "SSN 123-45-6789")

    out = mod.analyze_linked_artifact(url="https://example.test/scan.pdf")
    assert out["linked_artifact_type"] == "pdf"
    assert out["pii_detected"] is True
    assert out["linked_ocr_used"] is True
    assert "123-45-6789" in out["ssn_hits"]


def test_provider_candidate_urls_supports_qr_scanned_page(monkeypatch):
    from src.app.security import linked_artifact_analysis as mod

    def _fake_safe_request(method: str, url: str, **_: object):
        assert url == "https://qr.scanned.page/api/qr-code?uId=demo123"
        return SimpleNamespace(
            status_code=200,
            url=url,
            headers={"content-type": "application/json"},
            json=lambda: {"data": {"pdfUrl": "https://qr.scanned.page/uploads/demo.pdf"}},
        )

    monkeypatch.setattr(mod, "safe_request", _fake_safe_request)

    out = mod._provider_candidate_urls(source_url="https://qr.scanned.page/p/demo123")

    assert out == ["https://qr.scanned.page/uploads/demo.pdf"]


def test_linked_artifact_analysis_uses_offline_fixture_when_live_fetch_unavailable(monkeypatch, tmp_path):
    from src.app.security import linked_artifact_analysis as mod

    fixture = tmp_path / "offline-ssn.pdf"
    fixture.write_bytes(b"%PDF-1.7\n1 0 obj\n(SSN 123-45-6789)\nendobj\n")

    def _fake_safe_request(method: str, url: str, **_: object):
        raise RuntimeError("network blocked")

    monkeypatch.setattr(mod, "safe_request", _fake_safe_request)
    monkeypatch.setattr(
        mod,
        "_load_offline_fixture_map",
        lambda: {
            "entries": [
                {
                    "urls": ["https://scanned.page/p/R2g2Jb"],
                    "local_path": str(fixture),
                    "content_type": "application/pdf",
                    "filename": "offline-ssn.pdf",
                    "tag": "qr_ssn_offline_fixture",
                }
            ]
        },
    )

    out = mod.analyze_linked_artifact(url="https://scanned.page/p/R2g2Jb")

    assert out["linked_artifact_available"] is True
    assert out["linked_offline_fixture"] is True
    assert out["linked_offline_fixture_tag"] == "qr_ssn_offline_fixture"
    assert out["linked_attack_hypothesis"] == "linked_pii_exposure"
    assert out["pii_detected"] is True
    assert "ssn" in out["pii_type"]
