"""Required security submissions preserve their input and uncertain outcome."""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests


def _load():
    path = Path(__file__).parents[1] / "e2e/test_returns_adversarial_playwright.py"
    spec = importlib.util.spec_from_file_location("adversarial_fixture_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collecting_browser_scenario_preserves_parent_environment():
    before = dict(os.environ)
    _load()
    assert dict(os.environ) == before


def test_uncertain_submission_is_not_retried_or_skipped(monkeypatch, tmp_path):
    module = _load()
    images = [tmp_path / (str(i) + ".png") for i in range(4)]
    for path in images:
        path.write_bytes(b"synthetic test payload")
    post = Mock(side_effect=requests.exceptions.ReadTimeout("uncertain response"))
    monkeypatch.setattr(requests.Session, "post", post)
    with pytest.raises(requests.exceptions.ReadTimeout, match="uncertain response"):
        module._submit_case_via_api({"api_base_url": "http://127.0.0.1:1", "api_key": "synthetic"},
                                   [str(p) for p in images], "retain all evidence")
    assert post.call_count == 1
    assert len(post.call_args.kwargs["files"]) == 4
    assert all(file_tuple[1].closed for _, file_tuple in post.call_args.kwargs["files"])


def test_ui_start_failure_releases_owned_backend(monkeypatch, tmp_path, pytestconfig):
    module = _load()
    import tests.owned_security_runtime as backend

    closed = []

    @contextmanager
    def owned(*args, **kwargs):
        try:
            yield {"base_url": "http://127.0.0.1:1"}
        finally:
            closed.append(True)

    monkeypatch.setattr(backend, "_owned_runtime", owned)
    monkeypatch.setattr(module.shutil, "which", lambda _: "synthetic-node")
    monkeypatch.setattr(module.Path, "is_file", lambda _: True)
    monkeypatch.setattr(module.subprocess, "Popen", Mock(side_effect=OSError("UI failed")))
    factory = Mock()
    factory.mktemp.return_value = tmp_path
    with pytest.raises(OSError, match="UI failed"):
        next(module.live_stack.__wrapped__(pytestconfig, factory))
    assert closed == [True]
