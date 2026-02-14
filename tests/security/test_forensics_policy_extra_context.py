from src.app.services.forensics_policy import evaluate
from src.app.services.image_forensics import ForensicsResult


def _base_forensics() -> ForensicsResult:
    # Low-ish manipulation to avoid auto-deny path.
    return ForensicsResult(
        manipulation_score=0.3,
        splice_score=0.2,
        copy_move_score=0.0,
        double_compress_score=0.2,
        blur_score=0.0,
        metadata_flags=["missing_exif"],
        masks={},
        hashes={},
        explanations=[],
        details={},
    )


def test_prompt_injection_context_escalates() -> None:
    f = _base_forensics()
    out = evaluate(
        f,
        context={
            "evidence_tags": ["prompt_injection_text_suspected"],
            "prompt_injection_phrases": ["IGNORE POLICY", "admin override"],
        },
        ela_mask_area_ratio=0.0,
    )
    assert out["verdict"] == "request_more_data"
    assert "human_review" in (out.get("required_actions") or [])
    assert "quarantine_evidence" in (out.get("required_actions") or [])


def test_qr_suspicious_context_adds_do_not_follow_links() -> None:
    f = _base_forensics()
    out = evaluate(
        f,
        context={
            "evidence_tags": ["qr_url_present", "qr_url_suspicious"],
            "qr_risks": [{"url": "https://bit.ly/x", "risk": 0.7, "reasons": ["url_shortener"]}],
        },
        ela_mask_area_ratio=0.0,
    )
    assert out["verdict"] == "request_more_data"
    assert "do_not_follow_links" in (out.get("required_actions") or [])
    assert "human_review" in (out.get("required_actions") or [])

