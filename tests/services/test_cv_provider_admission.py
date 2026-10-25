from __future__ import annotations

import threading

import pytest


@pytest.mark.parametrize('size', [(2400, 800), (800, 2400)])
def test_identity_model_input_is_bounded_and_bound_to_original_image(monkeypatch, size):
    import base64
    import hashlib
    from io import BytesIO
    from PIL import Image
    from src.app.services import local_model_roles, model_transports
    captured = {}
    buffer = BytesIO()
    Image.new('RGB', size, 'white').save(buffer, format='PNG')
    original = buffer.getvalue()

    def transport(**kwargs):
        captured.update(kwargs)
        return lambda *args: 'unused'

    def execute(*args, **kwargs):
        captured['context_hash'] = kwargs.get('context_hash')
        return '{"labels":["laptop"],"text":"","category":"laptop"}'

    monkeypatch.setenv('CV_IDENTITY_MODEL_DIGEST', 'a' * 64)
    monkeypatch.setattr(model_transports, 'make_ollama_generate_transport', transport)
    monkeypatch.setattr(local_model_roles, 'execute_local_model_role', execute)
    result = cv_provider.ManagedCVProvider()._ollama_labels_and_text(original, mode='visual_search')
    with Image.open(BytesIO(base64.b64decode(captured['images'][0]))) as image:
        assert max(image.size) <= 512
        assert image.width / image.height == pytest.approx(size[0] / size[1], rel=.01)
    assert captured['context_hash'] == hashlib.sha256(original).hexdigest()
    assert result[0] == ['laptop']

from src.app.services import cv_provider


def test_ollama_provider_rejects_excess_work_before_network(monkeypatch):
    held_gate = threading.BoundedSemaphore(1)
    assert held_gate.acquire(blocking=False)
    monkeypatch.setattr(cv_provider, "_VISION_PROVIDER_GATE", held_gate)
    monkeypatch.setenv("CV_VISION_QUEUE_TIMEOUT_SEC", "0")
    provider = cv_provider.ManagedCVProvider()

    with pytest.raises(cv_provider.VisionProviderBusy):
        provider._ollama_labels_and_text(b"image", mode="visual_search")

    held_gate.release()


def test_browser_vision_uses_governed_digest_and_preserves_gateway_failure(monkeypatch):
    from src.app.services import local_model_roles as roles
    seen = []
    monkeypatch.setenv('CV_MODEL', 'reviewed-vision')
    monkeypatch.setenv('CV_IDENTITY_MODEL_DIGEST', 'a'*64)
    def execute(prompt, **kwargs):
        seen.append(kwargs)
        raise roles.LocalModelFailure('model_artifact_mismatch')
    monkeypatch.setattr(roles, 'execute_local_model_role', execute)
    with pytest.raises(roles.LocalModelFailure, match='model_artifact_mismatch'):
        cv_provider.ManagedCVProvider()._ollama_labels_and_text(b'image', mode='visual_search')
    assert seen[0]['model'] == 'reviewed-vision'
    assert seen[0]['digest'] == 'a'*64
    assert seen[0]['role'] == 'product_identity'
