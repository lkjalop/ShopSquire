import pytest
import time


def _request_with_retry(method, url, attempts=3, timeout=20, **kwargs):
    requests = pytest.importorskip("requests")
    last_exc = None
    for idx in range(attempts):
        try:
            return requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.ReadTimeout as exc:
            last_exc = exc
            if idx < attempts - 1:
                time.sleep(0.5 * (idx + 1))
                continue
            raise
    if last_exc:
        raise last_exc


def test_cv_escalation_rules_create_ticket(test_server):
    base = test_server["base_url"]
    headers = {"x-api-key": "local-merchant-key"}
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    files = {
        "images": ("test.png", image_bytes, "image/png"),
    }
    data = {
        "order_id": "ORDER-1",
        "issue_type": "refund",
        "description": "chargeback if no refund. fake product. manual review please",
    }
    r = _request_with_retry(
        "POST",
        base + "/api/v1/support/complaints/submit",
        headers=headers,
        files=files,
        data=data,
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("decision_id")
    assert j.get("evidence_id") is not None
    # Evidence export should be available when stored
    r2 = _request_with_retry(
        "GET",
        base + f"/api/v1/support/complaints/{j.get('case_id')}/evidence",
        headers=headers,
    )
    assert r2.status_code == 200
    ev = r2.json().get("evidence") or {}
    assert "ct_hashes" in ev
    assert "ocr_extract" in ev
