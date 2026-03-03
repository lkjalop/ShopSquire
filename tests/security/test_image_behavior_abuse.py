from __future__ import annotations

from typing import Any

from src.app.security.image_behavior_abuse import evaluate_behavioral_upload_abuse


class _RedisStub:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str):
        return self.data.get(key)

    def setex(self, key: str, _ttl: int, value: str):
        self.data[key] = value
        return True

    def incrby(self, key: str, amt: int):
        cur = int(float(self.data.get(key) or 0))
        cur += int(amt)
        self.data[key] = cur
        return cur

    def expire(self, _key: str, _ttl: int):
        return True


def test_behavioral_detector_flags_sybil_challenge():
    r = _RedisStub()
    now_ts = 1_700_000_000.0

    # Same IP, many rotating UIDs in one window => Sybil challenge.
    for i in range(7):
        evaluate_behavioral_upload_abuse(
            r,
            uid=f"anon-{i}",
            source_ip="203.0.113.10",
            asn=13335,
            image_hash=f"h-{i}",
            now_ts=now_ts,
        )

    out = evaluate_behavioral_upload_abuse(
        r,
        uid="anon-99",
        source_ip="203.0.113.10",
        asn=13335,
        image_hash="h-last",
        now_ts=now_ts,
    )
    assert out["verdict"] in {"challenge", "escalate"}
    assert (out.get("signals") or {}).get("ip_unique_uids", 0) >= 5
    if out["verdict"] == "challenge":
        assert bool((out.get("actions") or {}).get("captcha_required")) is True


def test_behavioral_detector_allows_after_captcha_pass(monkeypatch):
    r = _RedisStub()
    now_ts = 1_700_000_100.0
    monkeypatch.setenv("IMAGE_UPLOAD_CAPTCHA_TOKEN", "captcha-ok")

    # Build risk to force challenge.
    for i in range(6):
        evaluate_behavioral_upload_abuse(
            r,
            uid=f"anon-{i}",
            source_ip="198.51.100.22",
            asn=64512,
            image_hash=f"x-{i}",
            now_ts=now_ts,
        )

    challenged = evaluate_behavioral_upload_abuse(
        r,
        uid="anon-7",
        source_ip="198.51.100.22",
        asn=64512,
        image_hash="x-7",
        now_ts=now_ts,
    )
    assert challenged["verdict"] in {"challenge", "escalate"}

    # Same actor satisfies captcha token: challenge should be marked satisfied.
    passed = evaluate_behavioral_upload_abuse(
        r,
        uid="anon-7",
        source_ip="198.51.100.22",
        asn=64512,
        image_hash="x-8",
        captcha_token="captcha-ok",
        now_ts=now_ts,
    )
    if challenged["verdict"] == "challenge":
        assert passed["verdict"] == "allow"
        assert bool(((passed.get("signals") or {}).get("challenge_passed")))

