from concurrent.futures import ThreadPoolExecutor
import io
import threading
import time
import pytest

from fastapi.testclient import TestClient
from PIL import Image

from src.app.main import create_app


@pytest.mark.parametrize('slow_stage', ['tier2', 'object_storage'])
def test_slow_cv_work_does_not_block_unrelated_http_requests(monkeypatch, slow_stage):
    from src.app.routers import cv
    entered, release = threading.Event(), threading.Event()
    def slow_cv(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return {'verdict':{'verdict':'request_more_data'}, 'evidence_tags':[]}
    monkeypatch.setenv('CV_ASYNC_QUEUE_ENABLED', '0')
    monkeypatch.setenv('USE_S3_UPLOADS', '1' if slow_stage == 'object_storage' else '0')
    monkeypatch.setattr(cv, 'strict_image_ingest_gate', lambda **kwargs: {'blocked':False})
    monkeypatch.setattr(cv, 'run_tier2', slow_cv)
    if slow_stage == 'object_storage':
        class Storage:
            def upload_bytes(self, *args, **kwargs):
                slow_cv()
                return {'ok': True, 'url': 'fixture://stored'}
        monkeypatch.setattr(cv, 'get_default_storage', Storage)
        monkeypatch.setattr(cv, 'run_tier2', lambda *a, **k: {'verdict': {'verdict':'request_more_data'}})
    buffer = io.BytesIO(); Image.new('RGB',(16,16),'white').save(buffer,format='PNG')
    with TestClient(create_app()) as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, '/api/v1/cv/upload',
            files={'image':('fixture.png',buffer.getvalue(),'image/png')},
            headers={'x-api-key':'local-merchant-key'})
        assert entered.wait(3)
        timer = threading.Timer(0.7, release.set); timer.start()
        try:
            started = time.perf_counter()
            response = client.get('/healthz')
            elapsed = time.perf_counter()-started
            assert response.status_code == 200
            assert elapsed < 0.35, f'CV work blocked the event loop for {elapsed:.3f}s'
        finally:
            release.set(); timer.cancel()
            pending.result(timeout=5)
