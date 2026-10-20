import hashlib
from io import BytesIO
import json
from types import SimpleNamespace
import sys

from PIL import Image
import pytest

from src.app.services import cv_ocr


@pytest.fixture
def local_models(tmp_path, monkeypatch):
    manifest = {}
    for kind in ('detector', 'recognizer'):
        directory = tmp_path / kind
        directory.mkdir()
        files = {}
        for name in ('inference.json', 'inference.pdiparams', 'inference.yml'):
            value = (kind + ':' + name).encode()
            (directory / name).write_bytes(value)
            files[name] = hashlib.sha256(value).hexdigest()
        manifest[kind] = {'model_name': 'PP-OCRv5_mobile_' + ('det' if kind == 'detector' else 'rec'),
                          'directory': str(directory), 'files': files}
    path = tmp_path / 'models.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setenv('CV_PADDLE_MODEL_MANIFEST', str(path))
    return manifest


@pytest.fixture
def png():
    output = BytesIO()
    with Image.new('RGB', (8, 8), (255, 0, 0)) as image:
        image.save(output, format='PNG')
    return output.getvalue()


def test_paddle_three_predict_contract_uses_local_models_and_cpu(local_models, png, monkeypatch):
    calls = []

    class PaddleThree:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def predict(self, image):
            assert image.shape == (8, 8, 3)
            assert image[0, 0].tolist() == [0, 0, 255], 'Paddle image arrays use BGR'
            return [SimpleNamespace(json={'res': {'rec_texts': ['RAM 32 GB'], 'rec_scores': [0.94],
                'rec_polys': [[[0, 0], [7, 0], [7, 7], [0, 7]]]}})]

    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=PaddleThree))
    result = cv_ocr._paddle_ocr(png)
    assert result['text'] == 'RAM 32 GB', result
    assert result['confidence'] == pytest.approx(0.94)
    assert calls[0]['device'] == 'cpu'
    assert calls[0]['cpu_threads'] == 1
    assert calls[0]['enable_mkldnn'] is False, 'Pinned Paddle CPU graph must avoid unsupported oneDNN operators'
    assert calls[0]['text_detection_model_dir'] == local_models['detector']['directory']
    assert calls[0]['text_recognition_model_dir'] == local_models['recognizer']['directory']
    assert calls[0]['use_doc_orientation_classify'] is False


def test_missing_model_enrollment_never_constructs_a_downloading_default(png, monkeypatch):
    monkeypatch.delenv('CV_PADDLE_MODEL_MANIFEST', raising=False)
    calls = []
    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=lambda **kwargs: calls.append(kwargs)))
    result = cv_ocr._paddle_ocr(png)
    assert result['error'] == 'paddle_models_not_enrolled'
    assert result['text'] == '' and calls == []


def test_changed_model_bytes_are_rejected_before_inference(local_models, png, monkeypatch):
    from pathlib import Path
    (Path(local_models['detector']['directory']) / 'inference.pdiparams').write_bytes(b'changed')
    calls = []
    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=lambda **kwargs: calls.append(kwargs)))
    result = cv_ocr._paddle_ocr(png)
    assert result['error'] == 'paddle_model_artifact_mismatch'
    assert result['text'] == '' and calls == []


def test_paddle_worker_timeout_is_typed_and_releases_capacity(local_models, png, monkeypatch):
    from src.app.services import media_process_isolation as isolation
    calls = []

    def timed_out(**kwargs):
        calls.append(kwargs)
        return isolation.IsolatedMediaResult(status='timed_out')

    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', 'parent-value')
    monkeypatch.setattr(isolation, 'run_isolated_media_call', timed_out)
    for _ in range(2):
        assert cv_ocr.extract_text(png, provider='paddle')['error'] == 'paddle_ocr_timed_out'
    assert len(calls) == 2, 'Timeout must release the one-worker capacity slot'
    assert calls[0]['worker_env']['CUDA_VISIBLE_DEVICES'] == '-1'
    assert calls[0]['worker_env']['OMP_NUM_THREADS'] == '1'
    import os
    assert os.environ['CUDA_VISIBLE_DEVICES'] == 'parent-value'


def test_saturated_paddle_worker_does_not_spawn_another_model(local_models, png, monkeypatch):
    from src.app.services import media_process_isolation as isolation
    import threading
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_worker(**kwargs):
        calls.append(kwargs)
        started.set()
        assert release.wait(3)
        return isolation.IsolatedMediaResult(status='completed', value={'text': 'RAM 32 GB',
            'confidence': 0.94, 'boxes': [], 'provider': 'paddle'})

    monkeypatch.setattr(isolation, 'run_isolated_media_call', slow_worker)
    result = []
    owner = threading.Thread(target=lambda: result.append(cv_ocr.extract_text(png, provider='paddle')))
    owner.start()
    try:
        assert started.wait(3)
        assert cv_ocr.extract_text(png, provider='paddle')['error'] == 'paddle_worker_busy'
    finally:
        release.set()
        owner.join(3)
    assert not owner.is_alive()
    assert len(calls) == 1 and result[0]['text'] == 'RAM 32 GB'


@pytest.mark.parametrize('score,point', [(float('nan'), 0), (0.94, float('nan'))])
def test_nonfinite_model_output_cannot_become_ocr_evidence(local_models, png, monkeypatch, score, point):
    class InvalidPaddle:
        def __init__(self, **kwargs):
            pass

        def predict(self, image):
            return [{'rec_texts': ['RAM 32 GB'], 'rec_scores': [score],
                     'rec_polys': [[[point, 0], [7, 0], [7, 7], [0, 7]]]}]

    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=InvalidPaddle))
    result = cv_ocr._paddle_ocr(png)
    assert result['error'] == 'paddle_result_invalid'
    assert result['text'] == '' and result['boxes'] == []


def test_worker_launch_failure_is_typed_and_releases_capacity(local_models, png, monkeypatch):
    from src.app.services import media_process_isolation as isolation

    def cannot_spawn(**kwargs):
        raise OSError('owned-test-process-limit')

    monkeypatch.setattr(isolation, 'run_isolated_media_call', cannot_spawn)
    for _ in range(2):
        assert cv_ocr.extract_text(png, provider='paddle')['error'] == 'paddle_worker_failed'
