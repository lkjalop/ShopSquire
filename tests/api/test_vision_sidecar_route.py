from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from src.app.main import create_app


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
)


def test_vision_route_returns_visual_search_context(monkeypatch):
    import src.app.routers.image_sidecar as image_sidecar

    async def _fake_labels_and_text(self, _blob: bytes):
        return ["laptop", "computer"], ""

    def _fake_analyze(self, _labels, _text):
        return {"damage_type": "unknown", "severity": "undetermined", "confidence": 0.2}

    def _fake_abuse(*_args, **_kwargs):
        return {
            "verdict": "allow",
            "reason": "ok",
            "risk_score": 0.1,
            "signals": {},
            "actions": {"captcha_required": False, "auth_stepup_required": False, "soc_escalate": False, "reupload_needed": False},
            "challenge": {"required": False, "satisfied": False, "mode": None, "reason": None},
        }

    monkeypatch.setattr(image_sidecar.ManagedCVProvider, "get_labels_and_text", _fake_labels_and_text)
    monkeypatch.setattr(image_sidecar.BasicCVTriage, "analyze", _fake_analyze)
    monkeypatch.setattr(image_sidecar, "evaluate_behavioral_upload_abuse", _fake_abuse)

    client = TestClient(create_app())
    files = {"image": ("sample.png", _PNG_1X1, "image/png")}
    data = {"uid": "demo-user", "query": "find similar products like this"}
    r = client.post("/api/v1/vision/route", headers={"x-api-key": "local-merchant-key"}, files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("route") == "visual_search"
    assert body.get("security_verdict") == "allow"
    assert isinstance((body.get("context") or {}).get("labels"), list)


def test_vision_route_enforces_security_challenge(monkeypatch):
    import src.app.routers.image_sidecar as image_sidecar

    async def _fake_labels_and_text(self, _blob: bytes):
        return ["laptop"], ""

    def _fake_analyze(self, _labels, _text):
        return {"damage_type": "unknown", "severity": "minor", "confidence": 0.1}

    def _fake_abuse(*_args, **_kwargs):
        return {
            "verdict": "challenge",
            "reason": "captcha_required",
            "risk_score": 0.65,
            "signals": {"ip_sybil_rotation": True},
            "actions": {"captcha_required": True, "auth_stepup_required": False, "soc_escalate": False, "reupload_needed": False},
            "challenge": {"required": True, "satisfied": False, "mode": "captcha", "reason": "captcha_required"},
        }

    monkeypatch.setattr(image_sidecar.ManagedCVProvider, "get_labels_and_text", _fake_labels_and_text)
    monkeypatch.setattr(image_sidecar.BasicCVTriage, "analyze", _fake_analyze)
    monkeypatch.setattr(image_sidecar, "evaluate_behavioral_upload_abuse", _fake_abuse)

    client = TestClient(create_app())
    files = {"image": ("sample.png", _PNG_1X1, "image/png")}
    data = {"uid": "demo-user", "query": "find similar products"}
    r = client.post("/api/v1/vision/route", headers={"x-api-key": "local-merchant-key"}, files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("route") == "security_challenge"
    assert body.get("security_verdict") == "challenge"
    assert bool(((body.get("security") or {}).get("actions") or {}).get("captcha_required")) is True

