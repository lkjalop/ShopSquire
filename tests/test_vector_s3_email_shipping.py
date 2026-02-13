import os
from src.app.services.vector_store import PgVectorStore, get_default_vector_store
from src.app.services.storage_s3 import S3Storage, get_default_storage
from src.app.services.email_providers import SendGridProvider, SESProvider, get_default_email_provider
from src.app.services.shipping_providers import EasyPostProvider, ShipStationProvider, get_default_shipping_provider


def test_vector_store_stub(tmp_path, monkeypatch):
    # Ensure no engine available
    monkeypatch.setenv("DATABASE_URL", "sqlite:///does_not_exist.sqlite")
    vs = PgVectorStore()
    res = vs.index("test1", [0.1, 0.2, 0.3], {"meta": "x"})
    assert isinstance(res, dict)


def test_s3_storage_fallback(tmp_path, monkeypatch):
    # Ensure no AWS envs -> local fallback
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)
    s = S3Storage()
    data = b"hello"
    r = s.upload_bytes("test_upload.txt", data)
    assert isinstance(r, dict)


def test_email_providers_dev(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    sg = SendGridProvider()
    r = sg.send("dev@example.com", "sub", "body")
    assert isinstance(r, dict)


def test_shipping_providers_dev(monkeypatch):
    monkeypatch.delenv("EASYPOST_API_KEY", raising=False)
    ep = EasyPostProvider()
    r = ep.create_label({"to": "x"})
    assert isinstance(r, dict)
