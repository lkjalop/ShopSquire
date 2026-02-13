from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class VerticalPack:
    """Vertical configuration pack used by rules + CV/OCR pipelines.

    Keep this intentionally simple and JSON-serializable so packs can be loaded
    from config without code changes.
    """

    id: str
    version: str
    name: str
    required_views: Dict[str, Any]
    taxonomy: Dict[str, Any]
    allowed_substitutions: Dict[str, Any]
    thresholds: Dict[str, Any]
    ocr_patterns: Dict[str, Any]
    roi_allowlist: List[str]
    strict_required_views: bool = False

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "VerticalPack":
        return VerticalPack(
            id=str(d.get("id") or "unknown"),
            version=str(d.get("version") or "v1"),
            name=str(d.get("name") or d.get("id") or "unknown"),
            required_views=dict(d.get("required_views") or {}),
            taxonomy=dict(d.get("taxonomy") or {}),
            allowed_substitutions=dict(d.get("allowed_substitutions") or {}),
            thresholds=dict(d.get("thresholds") or {}),
            ocr_patterns=dict(d.get("ocr_patterns") or {}),
            roi_allowlist=list(d.get("roi_allowlist") or d.get("roi_classes") or []),
            strict_required_views=bool(d.get("strict_required_views", False)),
        )


def _packs_dir() -> Path:
    # Repo default is config/verticals/*.json
    return Path(os.getenv("VERTICAL_PACK_DIR", "config/verticals")).resolve()


@lru_cache(maxsize=64)
def load_vertical_pack(pack_id: str) -> VerticalPack:
    pack_id = (pack_id or "").strip() or "electronics"
    p = _packs_dir() / f"{pack_id}.json"
    if not p.exists():
        # Fall back to electronics.json if unknown
        p = _packs_dir() / "electronics.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return VerticalPack.from_dict(data)


@lru_cache(maxsize=1)
def list_vertical_packs() -> List[str]:
    d = _packs_dir()
    if not d.exists():
        return []
    return sorted([p.stem for p in d.glob("*.json") if p.is_file()])


def resolve_pack_id(request_headers: Optional[Dict[str, str]] = None, body: Optional[Dict[str, Any]] = None) -> str:
    """Resolve a pack id from request headers/body with a stable default."""
    body = body or {}
    hdrs = request_headers or {}
    for k in ("x-vertical-pack", "x-vertical", "x-vertical-id"):
        try:
            v = hdrs.get(k) or hdrs.get(k.upper())  # defensive for non-starlette callers
        except Exception:
            v = None
        if v:
            return str(v).strip()
    if body.get("vertical_pack"):
        return str(body.get("vertical_pack")).strip()
    if body.get("vertical"):
        return str(body.get("vertical")).strip()
    return "electronics"

