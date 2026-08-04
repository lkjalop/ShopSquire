from pathlib import Path

import pytest


REQUIRED_REAL_SAMPLES = (
    "apple-mac.jpg",
    "macbook-QR.png",
    "lenovo-pro7.webp",
)


@pytest.mark.certification
def test_cv_real_sample_pack_present_for_manual_certification():
    sample_dir = Path("dump") / "test-cv"
    missing = [name for name in REQUIRED_REAL_SAMPLES if not (sample_dir / name).is_file()]
    if missing:
        pytest.skip(
            "CV certification not run: local licensed/real sample pack is absent; "
            f"missing={missing}"
        )
    assert all((sample_dir / name).stat().st_size > 0 for name in REQUIRED_REAL_SAMPLES)
