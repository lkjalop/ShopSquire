from src.app.services import audit_chain


def test_azure_blob_anchor_uses_append_only_object_key(monkeypatch):
    uploads = []

    class _Storage:
        def upload_bytes(self, key, data, content_type=None):
            uploads.append((key, data, content_type))
            return {"ok": True}

    monkeypatch.setenv("AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE", "azure_blob")
    monkeypatch.setattr(
        "src.app.services.storage_s3.get_default_storage", lambda: _Storage()
    )

    audit_chain._append_external_anchor(
        {
            "id": "anchor-123",
            "created_at": "2026-08-01T00:00:00Z",
            "merkle_root": "root",
            "prev_signature": "previous",
            "signature": "signed",
        }
    )

    assert len(uploads) == 1
    assert uploads[0][0].endswith("/anchor-123.json")
    assert uploads[0][2] == "application/json"
