from __future__ import annotations

import threading

import pytest

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
