"""Cached image analysis must preserve request ownership and security context."""
from copy import deepcopy

import pytest

from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.services import cv_tier2_pipeline as pipeline
from src.app.services import vision_cache


@pytest.fixture(autouse=True)
def private_cache(monkeypatch):
    monkeypatch.setenv("VISION_CACHE_ENABLED", "1")
    monkeypatch.setattr(vision_cache, "_CACHE", {})


@pytest.mark.parametrize("changed", [
    {"case_id": "case-b"}, {"description": "a different buyer workload"},
    {"filename": "different.png"}, {"order_ctx": {"found": False}},
])
def test_same_image_does_not_reuse_another_request_context(monkeypatch, changed):
    calls = []

    def analyze(image, *, meta, pack_id):
        calls.append(deepcopy(meta))
        return {"context": deepcopy(meta), "case_id": meta["case_id"]}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    first = dict(case_id="case-a", description="buyer workload", filename="original.png")
    second = {**first, **changed}
    assert pipeline.run_tier2(b"same-image", meta=first)["context"] == first
    assert pipeline.run_tier2(b"same-image", meta=second)["context"] == second
    assert len(calls) == 2


def test_active_tenant_is_part_of_cache_ownership(monkeypatch):
    calls = []
    from src.app.platform.tenant_context import current_tenant_id

    def analyze(*args, **kwargs):
        calls.append(current_tenant_id())
        return {"tenant": current_tenant_id()}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    for tenant in ("tenant-a", "tenant-b"):
        token = set_active_tenant_id(tenant)
        try:
            assert pipeline.run_tier2(b"same-image")["tenant"] == tenant
        finally:
            reset_active_tenant_id(token)
    assert calls == ["tenant-a", "tenant-b"]


def test_returned_nested_result_cannot_change_the_cached_verdict(monkeypatch):
    calls = []

    def analyze(*args, **kwargs):
        calls.append(True)
        return {"robustness": {"steganography": {"is_suspicious": True}}}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    first = pipeline.run_tier2(b"same-image")
    first["robustness"]["steganography"]["is_suspicious"] = False
    second = pipeline.run_tier2(b"same-image")
    assert second["robustness"]["steganography"]["is_suspicious"] is True
    second["robustness"].clear()
    assert pipeline.run_tier2(b"same-image")["robustness"]["steganography"]["is_suspicious"] is True
    assert calls == [True]


def test_security_configuration_change_forces_fresh_analysis(monkeypatch):
    calls = []

    def analyze(*args, **kwargs):
        import os
        calls.append(os.environ["CV_STEG_DETECT_ENABLED"])
        return {"enabled": calls[-1]}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    for enabled in ("0", "1"):
        monkeypatch.setenv("CV_STEG_DETECT_ENABLED", enabled)
        assert pipeline.run_tier2(b"same-image")["enabled"] == enabled
    assert calls == ["0", "1"]


def test_failed_detector_is_retried_instead_of_reusing_partial_analysis(monkeypatch):
    calls = []

    def analyze(*args, **kwargs):
        calls.append(True)
        return {"robustness": {"steganography": {"error": "owned-detector-unavailable"}}}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    pipeline.run_tier2(b"same-image")
    pipeline.run_tier2(b"same-image")
    assert len(calls) == 2


def test_identical_context_keeps_the_valid_cache_hit(monkeypatch):
    calls = []

    def analyze(*args, **kwargs):
        calls.append(True)
        return {"case_id": "case-a", "evidence_tags": ["owned-control"]}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    first = pipeline.run_tier2(b"same-image", meta={"case_id": "case-a", "description": "same"})
    second = pipeline.run_tier2(b"same-image", meta={"description": "same", "case_id": "case-a"})
    assert second == first
    assert len(calls) == 1


def test_pack_definition_change_forces_fresh_analysis(monkeypatch):
    definition = {"revision": "first"}
    calls = []
    monkeypatch.setattr(pipeline, "get_model_pack", lambda _: dict(definition))

    def analyze(*args, **kwargs):
        calls.append(True)
        return {"revision": definition["revision"]}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    assert pipeline.run_tier2(b"same-image")["revision"] == "first"
    definition["revision"] = "second"
    assert pipeline.run_tier2(b"same-image")["revision"] == "second"
    assert len(calls) == 2


def test_unsupported_context_bypasses_cache_without_changing_analysis(monkeypatch):
    calls = []

    def analyze(*args, **kwargs):
        calls.append(True)
        return {"result": "computed"}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    meta = {"case_id": "case-a", "non_json_value": object()}
    assert pipeline.run_tier2(b"same-image", meta=meta) == {"result": "computed"}
    assert pipeline.run_tier2(b"same-image", meta=meta) == {"result": "computed"}
    assert len(calls) == 2


def test_configuration_changed_during_analysis_is_not_cached_under_the_old_context(monkeypatch):
    definition = {"revision": "first"}
    calls = []
    monkeypatch.setattr(pipeline, "get_model_pack", lambda _: dict(definition))

    def analyze(*args, **kwargs):
        calls.append(True)
        definition["revision"] = "second"
        return {"revision": "second"}

    monkeypatch.setattr(pipeline, "_run_tier2_impl", analyze)
    pipeline.run_tier2(b"same-image")
    definition["revision"] = "first"
    pipeline.run_tier2(b"same-image")
    assert len(calls) == 2
