import builtins
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.app import main


@pytest.fixture
def provider_packages(monkeypatch):
    import importlib.util
    original_import = builtins.__import__
    attempted = []
    def guarded_import(name, *args, **kwargs):
        if name in {'paddleocr', 'paddle', 'cv2', 'pytesseract'}:
            attempted.append(name)
            return SimpleNamespace()
        return original_import(name, *args, **kwargs)
    original_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name, *args:
        SimpleNamespace() if name in {'paddleocr', 'paddle', 'cv2', 'pytesseract'} else original_spec(name, *args))
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    monkeypatch.delenv('CV_PADDLE_MODEL_MANIFEST', raising=False)
    return attempted


@pytest.fixture
def enrolled_models(tmp_path, monkeypatch):
    manifest = {}
    for kind in ('detector', 'recognizer'):
        directory = tmp_path / kind
        directory.mkdir()
        files = {}
        for name in ('inference.json', 'inference.pdiparams', 'inference.yml'):
            data = (kind + name).encode('utf-8')
            (directory / name).write_bytes(data)
            files[name] = hashlib.sha256(data).hexdigest()
        manifest[kind] = {'model_name': 'PP-OCRv5_mobile_' + ('det' if kind == 'detector' else 'rec'),
                          'directory': str(directory), 'files': files}
    path = tmp_path / 'models.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setenv('CV_PADDLE_MODEL_MANIFEST', str(path))
    return manifest


def test_paddle_libraries_alone_cannot_claim_ocr_readiness(provider_packages):
    snapshot = main._cv_ocr_runtime_snapshot('paddle')
    assert snapshot['ready'] is False
    assert 'paddle_models_not_enrolled' in snapshot['reasons']


def test_enrolled_asset_readiness_never_imports_the_inference_framework(provider_packages, enrolled_models):
    snapshot = main._cv_ocr_runtime_snapshot('paddle')
    assert snapshot['ready'] is True, snapshot
    assert provider_packages == [], 'An availability probe must not start the native framework or its network checks'


def test_tampered_model_assets_cannot_be_reported_ready(provider_packages, enrolled_models):
    from pathlib import Path
    (Path(enrolled_models['detector']['directory']) / 'inference.pdiparams').write_bytes(b'changed')
    snapshot = main._cv_ocr_runtime_snapshot('paddle')
    assert snapshot['ready'] is False
    assert 'paddle_model_artifact_mismatch' in snapshot['reasons']


def test_tesseract_binary_must_pass_its_version_probe(monkeypatch, provider_packages):
    monkeypatch.setattr(main.shutil, 'which', lambda command: 'broken-tesseract.exe')
    monkeypatch.setattr(main.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1))
    snapshot = main._cv_ocr_runtime_snapshot('tesseract')
    assert snapshot['ready'] is False
    assert 'tesseract_version_probe_failed' in snapshot['reasons']


def test_model_file_list_is_rejected_as_an_invalid_manifest(enrolled_models, monkeypatch):
    from src.app.services.paddle_model_assets import local_paddle_models, PaddleAssetError
    from pathlib import Path
    import os
    manifest = Path(os.environ['CV_PADDLE_MODEL_MANIFEST'])
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['detector']['files'] = list(data['detector']['files'])
    manifest.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(PaddleAssetError, match='paddle_model_manifest_invalid'):
        local_paddle_models()
