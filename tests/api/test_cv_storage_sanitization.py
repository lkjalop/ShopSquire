import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.app.main import create_app


@pytest.mark.parametrize('scanner_failed', [False, True])
def test_optional_object_storage_never_receives_unsanitized_upload(monkeypatch, scanner_failed):
    from src.app.routers import cv
    from src.app.services import image_intake
    image = Image.new('RGB', (16, 16), 'white')
    exif = Image.Exif(); exif[270] = 'PRIVATE_CAMERA_CANARY'
    buffer = io.BytesIO(); image.save(buffer, format='JPEG', exif=exif)
    original = buffer.getvalue()
    uploaded = []
    class Storage:
        def upload_bytes(self, key, data, **kwargs):
            uploaded.append(data)
            return {'ok':True, 'url':'fixture://sanitized'}
    monkeypatch.setenv('USE_S3_UPLOADS', '1')
    monkeypatch.setenv('CV_ASYNC_QUEUE_ENABLED', '1')
    monkeypatch.setattr(cv, 'get_default_storage', lambda: Storage())
    monkeypatch.setattr(cv, 'strict_image_ingest_gate', lambda **kwargs: {'blocked':False})
    monkeypatch.setattr('src.app.workers.rq_queue.enqueue_cv', lambda payload: 'fixture-job')
    if scanner_failed:
        def fails(blob):
            raise RuntimeError('sanitizer unavailable')
        monkeypatch.setattr(image_intake, 'sanitize_image', fails)
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/cv/upload',
            files={'image':('camera.jpg', original, 'image/jpeg')},
            headers={'x-api-key':'local-merchant-key'})
    assert response.status_code == 200, response.text
    if scanner_failed:
        assert uploaded == []
    else:
        assert len(uploaded) == 1
        assert uploaded[0] != original
        assert b'PRIVATE_CAMERA_CANARY' not in uploaded[0]
        with Image.open(io.BytesIO(uploaded[0])) as stored:
            assert stored.size == (16, 16)
