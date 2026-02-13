import base64


def test_vision_triage_image_upload(page, test_server, monkeypatch):
    base = test_server["base_url"]
    # Use Playwright request to POST a small fake PNG as multipart with x-api-key
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
    )
    headers = { 'x-api-key': 'local-merchant-key' }
    # Playwright's request API supports multipart via 'multipart' kw; use data param
    b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
    # Stub classifier to deterministic result for test server (server runs in-thread)
    try:
        from src.app.services.cv_triage_basic import BasicCVTriage

        def _deterministic_analyze(self, labels, extracted_text):
            return {
                "status": "analyzed",
                "damage_type": "functional",
                "component": "display",
                "confidence": 0.9,
                "raw_labels": labels,
            }

        monkeypatch.setattr(BasicCVTriage, "analyze", _deterministic_analyze)
    except Exception:
        pass

    # Use Python requests to post multipart directly (avoids browser CORS/multipart issues)
    import requests
    files = {'image': ('test.png', png_bytes, 'image/png')}
    r = requests.post(base + '/api/v1/vision/triage', headers={'x-api-key': 'local-merchant-key'}, files=files)
    assert r.status_code == 200
    j = r.json()
    assert j.get('label') == 'device' or 'query' in j
    # Ensure persistence: event_id returned and is a UUID-like string
    assert 'event_id' in j and isinstance(j.get('event_id'), str) and len(j.get('event_id')) > 8
