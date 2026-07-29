from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/golden/recommend_v1_archive_manifest.json"


def _sha256(path: Path) -> str:
    # The sealed evidence paths are marked `-text` in .gitattributes, so Git
    # preserves their exact archived bytes on every platform.
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_legacy_recommend_router_is_non_importable_and_hash_sealed() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    router = manifest["legacy_router"]
    characterization = manifest["legacy_characterization"]

    assert not (ROOT / "src/app/routers/recommend.py").exists()
    assert not (ROOT / "src/app/services/legacy_recommendation_delegate.py").exists()
    assert _sha256(ROOT / router["archived_path"]) == router["sha256"]
    assert (
        _sha256(ROOT / characterization["archived_path"])
        == characterization["sha256"]
    )


def test_frozen_suite_is_not_presented_as_current_green_evidence() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    evidence = manifest["legacy_characterization"]

    assert evidence["collected_tests"] == 62
    assert sum(evidence["last_observed"].values()) == 62
    assert evidence["last_observed"]["failed"] == 36
    assert evidence["status"] == "non_executable_historical_evidence"
