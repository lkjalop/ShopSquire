from __future__ import annotations

import asyncio
from src.app.services.cv_tiered import TieredCV


def test_tieredcv_process_minimal_png_bytes():
    # minimal PNG-like header plus filler to pass size checks
    content = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 512)
    cv = TieredCV()
    result = asyncio.run(cv.process(content, meta={"phash": "deadbeef"}, trace_id=None))

    assert isinstance(result, dict)
    assert result.get("tiered") is True
    # Required tiers present
    assert "tier0" in result and "tier1" in result and "tier2" in result
    assert isinstance(result.get("total_latency_ms"), int)
    assert isinstance(result.get("escalated"), bool)

    t0 = result.get("tier0", {})
    assert "size_bytes" in t0
    # Tier2 should expose keys even if underlying providers are unavailable
    t2 = result.get("tier2", {})
    assert "reverse_hits" in t2 and "serial" in t2 and "forensics" in t2
