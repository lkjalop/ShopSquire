"""Tier 3 — image<->query relationship classifier + visual-similarity stage (pure)."""
from __future__ import annotations

from src.app.services.image_query_relationship import ADJACENT, OFF_TOPIC, ON_TOPIC, classify
from src.app.services.recommend_image_similarity_stage import run as run_visual

# fake category detector: image_labels[0] = type; first query word = type
def _dc(query=None, image_labels=None):
    if image_labels:
        return str(image_labels[0])
    return str(query or "").split()[0] if query else ""

_COMP = {"laptop": ["bag", "audio"], "bag": ["laptop"]}


def test_same_type_is_on_topic_boost():
    r = classify(image_labels=["laptop"], query="laptop under 1800", detect_category=_dc, companions_map=_COMP)
    assert r["relationship"] == ON_TOPIC and r["influence"] == "boost"


def test_companion_type_is_adjacent_hint():
    # laptop image + bag query -> bag is a companion of laptop -> adjacent (hint, not override)
    r = classify(image_labels=["laptop"], query="bag for it", detect_category=_dc, companions_map=_COMP)
    assert r["relationship"] == ADJACENT and r["influence"] == "hint"


def test_unrelated_type_is_off_topic():
    r = classify(image_labels=["laptop"], query="medicine for headache", detect_category=_dc, companions_map=_COMP)
    assert r["relationship"] == OFF_TOPIC and r["influence"] == "none"


def test_suspicious_and_no_signal_are_off_topic():
    assert classify(image_labels=["laptop"], query="laptop", image_suspicious=True, detect_category=_dc)["relationship"] == OFF_TOPIC
    assert classify(image_labels=[], query="laptop", detect_category=_dc)["relationship"] == OFF_TOPIC


# ── visual stage ──
def _fake_search(**kw):
    return [{"sku": f"V{i}"} for i in range(10)]


def test_stage_on_topic_returns_labeled_candidates():
    rel = {"relationship": ON_TOPIC, "influence": "boost"}
    out = run_visual(image_bytes=b"x", query_text="laptop", relationship=rel, search_fn=_fake_search)
    assert len(out["candidates"]) == 10 and out["candidates"][0]["source"] == "visual_similarity"
    assert out["source_status"]["source"] == "visual_similarity"


def test_stage_adjacent_caps_to_hints():
    rel = {"relationship": ADJACENT, "influence": "hint"}
    out = run_visual(image_bytes=b"x", query_text="bag", relationship=rel, search_fn=_fake_search)
    assert len(out["candidates"]) == 3  # adjacent -> a few hints only


def test_stage_off_topic_and_gate_denied_return_nothing():
    assert run_visual(image_bytes=b"x", query_text="q", relationship={"relationship": OFF_TOPIC}, search_fn=_fake_search)["candidates"] == []
    on = {"relationship": ON_TOPIC, "influence": "boost"}
    assert run_visual(image_bytes=b"x", query_text="q", relationship=on, allow_visual=False, search_fn=_fake_search)["candidates"] == []


def test_stage_search_error_fails_safe():
    def _boom(**kw):
        raise RuntimeError("no index")
    out = run_visual(image_bytes=b"x", query_text="q", relationship={"relationship": ON_TOPIC}, search_fn=_boom)
    assert out["candidates"] == [] and out["source_status"]["status"] == "error"
