from __future__ import annotations

from src.app.services.kb_integrity import verify_kb_signature, write_signed_kb


def test_kb_signature_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_SIGNING_KEY", "test-kb-key")
    p = tmp_path / "faq_kb.json"
    write_signed_kb(str(p), b"[{\"id\":\"1\"}]")
    assert verify_kb_signature(str(p)) is True


def test_kb_signature_fails_on_tamper(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_SIGNING_KEY", "test-kb-key")
    p = tmp_path / "faq_kb.json"
    write_signed_kb(str(p), b"[{\"id\":\"1\"}]")
    p.write_text('[{"id":"2"}]', encoding="utf-8")
    assert verify_kb_signature(str(p)) is False
