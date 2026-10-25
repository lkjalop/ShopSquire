"""Passive image evidence must not assert an unrelated or executed technique."""

from src.app.security.passive_payload_analysis import classify_passive_payload


def test_unrecovered_steg_maps_to_steganography_without_binary_padding_or_execution():
    result = classify_passive_payload(
        filename="product.png", extracted_text="",
        signals={"steg_suspicious": True, "steg_score": 0.8},
    )
    assert result["attack_hypothesis"] == "steg_unknown_payload"
    assert "T1027.003" in result["possible_mitre_attack"]
    assert "T1027.001" not in result["possible_mitre_attack"]
    assert result["mitre_attack"] == []
    assert result["evidence_lane"] == "passive_artifact_signal_only"


def test_clean_image_does_not_invent_steganography_from_its_filename():
    result = classify_passive_payload(
        filename="steg-c2-product.png", extracted_text="", signals={},
    )
    assert result["attack_hypothesis"] == "unknown"
    assert "T1027.003" not in result["possible_mitre_attack"]
    assert result["mitre_attack"] == []
