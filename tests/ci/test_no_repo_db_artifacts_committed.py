from __future__ import annotations

import subprocess


def test_no_db_artifacts_tracked_in_git():
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        # Non-git environments (e.g., source tarball) skip this guard.
        return
    tracked = [x.strip() for x in (res.stdout or "").splitlines() if x.strip()]
    bad = []
    for p in tracked:
        low = p.lower()
        if low.endswith(".db") or low.endswith(".sqlite") or low.endswith(".sqlite-journal"):
            bad.append(p)
    assert bad == [], f"Tracked DB artifacts must be removed: {bad}"

