"""Guard: no hardcoded demo/dev API key may ship in a built frontend bundle.

DecisionTrace once carried a `local-merchant-key` fallback bundled into the shopper build (GPT-5.5
audit #2). The source is fixed, but a STALE `dist/` kept the key — a real exposure if that bundle is
served. This test greps any present build output for the forbidden token and fails if found. It SKIPS
when no dist exists (bare CI without a frontend build) so it never blocks a backend-only run — but the
moment a bundle is built (locally or in a release pipeline), a leaked key fails the suite.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# tokens that must never appear in a shipped bundle
_FORBIDDEN = ("local-merchant-key",)

# candidate build-output roots (shopper + admin)
_DIST_DIRS = (
    Path("frontend/dist"),
    Path("src/frontend/admin-react/dist"),
)


def _built_dirs():
    return [d for d in _DIST_DIRS if d.is_dir()]


@pytest.mark.skipif(not _built_dirs(), reason="no frontend dist built — nothing to scan")
def test_no_bundled_demo_key_in_dist():
    offenders = []
    for d in _built_dirs():
        for f in d.rglob("*.js"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for token in _FORBIDDEN:
                if token in text:
                    offenders.append(f"{f}: contains '{token}'")
    assert not offenders, (
        "A hardcoded demo key leaked into a built frontend bundle — rebuild the dist from the fixed "
        "source before shipping:\n  " + "\n  ".join(offenders)
    )
