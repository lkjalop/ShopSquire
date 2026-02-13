import pytest
from src.app.services.image_forensics import ImageForensicsService, ForensicsResult


def test_corpus_struct_and_ranges(golden_corpus):
    svc = ImageForensicsService()
    for name, buf in golden_corpus.items():
        r = svc.analyze(buf)
        assert isinstance(r, ForensicsResult)
        # numeric fields in [0,1]
        for v in (
            r.manipulation_score,
            r.splice_score,
            r.copy_move_score,
            r.double_compress_score,
            r.blur_score,
        ):
            assert isinstance(v, float)
            assert 0.0 <= v <= 1.0
        # masks and hashes exist (may be empty dicts/lists but present)
        assert hasattr(r, "masks")
        assert hasattr(r, "hashes")


def test_splice_vs_base(golden_corpus):
    svc = ImageForensicsService()
    base = svc.analyze(golden_corpus["base"])
    splice = svc.analyze(golden_corpus["spliced"])
    assert splice.manipulation_score >= base.manipulation_score
    assert splice.splice_score >= base.splice_score


def test_recompressed_not_excessively_flagged(golden_corpus):
    svc = ImageForensicsService()
    base = svc.analyze(golden_corpus["base"])
    recompr = svc.analyze(golden_corpus["recompressed"])    
    # recompression may raise double_compress_score but should not exceed 0.9 by default
    assert 0.0 <= recompr.double_compress_score <= 1.0
    assert recompr.double_compress_score <= 0.95
