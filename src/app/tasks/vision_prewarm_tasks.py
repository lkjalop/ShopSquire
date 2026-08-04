"""Scheduled vision-cache prewarm (N5, 2026-07-07). The sha256 vision cache is process-local, so the
FIRST image after every backend restart paid the full VLM cost (50-86s cold). This beat task warms the
demo/test image set on a schedule so a restart never hands a buyer the cold path. Default-OFF
(VISION_PREWARM_ENABLED); image dir via VISION_PREWARM_DIR (default dump/test-cv)."""
from __future__ import annotations

import logging
import os

from src.app.workers.celery_app import celery_app

_log = logging.getLogger("shopsquire.vision_prewarm")


@celery_app.task(name="src.app.tasks.vision_prewarm_tasks.prewarm_vision_cache")
def prewarm_vision_cache() -> dict:
    directory = os.getenv("VISION_PREWARM_DIR", os.path.join("dump", "test-cv"))
    warmed = failed = 0
    try:
        from scripts.prewarm_demo_vision_cache import _discover_images, _warm_one
        for path in _discover_images(directory):
            try:
                ok = _warm_one(path, identity_only=True)
                warmed += 1 if ok else 0
                failed += 0 if ok else 1
            except Exception:
                failed += 1
    except Exception as exc:
        _log.warning("vision prewarm unavailable: %s", exc)
        return {"warmed": 0, "failed": 0, "error": str(exc)[:160]}
    _log.info("vision prewarm: warmed=%s failed=%s dir=%s", warmed, failed, directory)
    return {"warmed": warmed, "failed": failed}
