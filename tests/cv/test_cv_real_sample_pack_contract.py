from pathlib import Path


REQUIRED_REAL_SAMPLES = (
    "apple-mac.jpg",
    "macbook-QR.png",
    "lenovo-pro7.webp",
)


def test_cv_real_sample_pack_present():
    sample_dir = Path("dump") / "test-cv"
    missing = [name for name in REQUIRED_REAL_SAMPLES if not (sample_dir / name).is_file()]
    assert not missing, f"Missing required real CV sample pack files in {sample_dir}: {missing}"
