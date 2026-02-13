from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from src.app.services.returns import image_phash_hex, image_sha256_bytes, check_image_reuse


@dataclass
class HashReuseResult:
    any_reused: bool
    images: List[Dict[str, Any]]


def assess_hash_reuse(images: List[Tuple[str, bytes]]) -> HashReuseResult:
    out: List[Dict[str, Any]] = []
    any_reused = False
    for fname, b in images or []:
        sha = image_sha256_bytes(b)
        ph = image_phash_hex(b)
        reused = check_image_reuse(ph)
        any_reused = any_reused or bool(reused)
        out.append({"filename": fname, "sha256": sha, "phash": ph, "reused": bool(reused)})
    return HashReuseResult(any_reused=any_reused, images=out)

