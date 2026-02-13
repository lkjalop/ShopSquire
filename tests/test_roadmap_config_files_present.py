import re
from pathlib import Path


def test_roadmap_referenced_config_json_files_exist():
    """Prevent silent drift between roadmap and repo.

    This test enforces that any `config/...*.json` or `src/...*.json` file
    referenced in `docs/PRODUCT_AGNOSTIC_PLATFORM_ROADMAP.md` exists.
    """
    root = Path(__file__).resolve().parents[1]
    roadmap = root / "docs" / "PRODUCT_AGNOSTIC_PLATFORM_ROADMAP.md"
    text = roadmap.read_text(encoding="utf-8")

    paths = []
    for p in re.findall(r"`([^`]+\\.json)`", text):
        if p.startswith(("config/", "src/")):
            paths.append(p)
    paths = sorted(set(paths))

    missing = [p for p in paths if not (root / p).exists()]
    assert not missing, f"Roadmap references missing JSON files: {missing}"

