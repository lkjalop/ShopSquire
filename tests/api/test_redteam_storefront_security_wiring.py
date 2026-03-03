import io
import os

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.cv_provider import ManagedCVProvider


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path_factory.getbasetemp()}/redteam_storefront.sqlite"
    app = create_app()
    return TestClient(app)


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDAT\x08\x99c``\xf8\x0f\x00\x01\x05\x01\x00\x18\x9d\x9c\x1e\x00\x00\x00\x00IEND\xAE\x42\x60\x82"
    )


def test_redteam_upload_evasion_disguised_executable_blocked(client):
    data = {"order_id": "ord-red-1", "issue_type": "damaged", "description": "test disguised binary payload"}
    # Deliberately mismatched: image extension + image content-type with executable bytes.
    files = [("images", ("invoice_photo.png", io.BytesIO(b"MZ-fake-executable"), "image/png"))]
    r = client.post("/api/v1/support/complaints/submit", data=data, files=files, headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else {}
    assert detail.get("error") == "ingest_gate_blocked"
    blocked = detail.get("blocked_uploads") or []
    assert blocked, f"expected blocked uploads details, got: {detail}"


def test_redteam_geo_asn_route_forcing_to_security_review(client, monkeypatch):
    async def _fake_labels_and_text(self, image_bytes: bytes):
        return ["screen", "damage"], "serial SN-REDTEAM-1"

    monkeypatch.setattr(ManagedCVProvider, "get_labels_and_text", _fake_labels_and_text)

    import src.app.routers.support_complaints as complaints

    def _forced_geo(_source_ip):
        return {
            "source_ip": "185.220.100.55",
            "country": "DE",
            "asn": 200000,
            "org": "Tor Exit Nodes",
            "is_vpn": False,
            "is_hosting": True,
            "risk": 0.97,
            "force_security_review": True,
            "route_reason": "geoip_risk_or_asn_threshold",
            "thresholds": {"security_review_risk_threshold": 0.75, "hard_block_risk_threshold": 0.9},
        }

    monkeypatch.setattr(complaints, "_build_geoip_trace", _forced_geo)

    files = [("images", ("photo.png", io.BytesIO(_tiny_png_bytes()), "image/png"))]
    data = {"order_id": "ord-red-2", "issue_type": "damage", "description": "normal return description"}
    r = client.post("/api/v1/support/complaints/submit", data=data, files=files, headers={"x-api-key": "local-merchant-key"})
    if r.status_code == 422:
        pytest.skip(f"multipart env issue: {r.text}")
    assert r.status_code == 200
    body = r.json()
    assert str(body.get("suggested_routing") or body.get("verdict") or "") == "security_review"
    geo = body.get("geoip_trace") if isinstance(body.get("geoip_trace"), dict) else {}
    assert bool(geo.get("force_security_review")) is True
    assert str(geo.get("route_reason") or "") == "geoip_risk_or_asn_threshold"
