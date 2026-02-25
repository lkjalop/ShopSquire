from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _pkg_set(sbom: dict) -> set[str]:
    out: set[str] = set()
    for pkg in sbom.get("packages") or []:
        if not isinstance(pkg, dict):
            continue
        name = str(pkg.get("name") or "").strip()
        version = str(pkg.get("versionInfo") or "").strip()
        if name:
            out.add(f"{name}@{version}" if version else name)
    return out


def main() -> int:
    current_path = Path(os.getenv("SBOM_CURRENT", "sbom.spdx.json"))
    baseline_path = Path(os.getenv("SBOM_BASELINE", "config/security/sbom-baseline.spdx.json"))

    if not current_path.exists():
        print(f"current SBOM not found: {current_path}")
        return 1
    if not baseline_path.exists():
        print(f"baseline SBOM not found: {baseline_path}; skipping diff")
        return 0

    cur = _pkg_set(_load(current_path))
    base = _pkg_set(_load(baseline_path))
    added = sorted(cur - base)
    removed = sorted(base - cur)

    max_report = int(os.getenv("SBOM_DIFF_MAX_REPORT", "80") or 80)
    print(f"SBOM diff: +{len(added)} / -{len(removed)}")
    if added:
        print("Added packages:")
        for x in added[:max_report]:
            print(f"  + {x}")
    if removed:
        print("Removed packages:")
        for x in removed[:max_report]:
            print(f"  - {x}")

    fail_on_diff = str(os.getenv("SBOM_DIFF_FAIL_ON_CHANGE", "0") or "0").lower() in ("1", "true", "yes")
    if fail_on_diff and (added or removed):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
