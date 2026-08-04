#!/usr/bin/env python
"""Backfill structured GPU specs (gpu, gpu_discrete, gpu_vram_gb) from product NAMES.

2026-07-07 audit finding: only 9 of 113 active products carried specs.gpu_discrete — the catalog's
RTX 5080/5090 machines existed only as name strings, so the ml/ai hard filter could not SEE them:
"training llm models, $3500" returned 1 product (the cheapest 4060) while a $3,499 RTX 5060 and
above-budget 5080/5090 sat invisible. Retrieval and ranking are only as smart as the specs data.

Vertical note: this is an ELECTRONICS data script (scripts/ are not agnostic-core; GPU model literals
belong here + in profile data, never in core services). Idempotent: existing spec keys are preserved;
only missing gpu fields are filled. Dry run by default; --apply writes.

    python -m scripts.backfill_gpu_specs            # report what would change
    python -m scripts.backfill_gpu_specs --apply    # write
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Laptop-variant VRAM by GPU model (GB). Conservative/common configs.
_VRAM_GB = {
    "3050": 6, "3060": 6, "3070": 8, "3080": 8,
    "4050": 6, "4060": 8, "4070": 8, "4080": 12, "4090": 16,
    "5050": 8, "5060": 8, "5070": 8, "5080": 16, "5090": 24,
}
_GPU_RE = re.compile(r"\b(?:GeForce\s+)?(RTX|GTX)\s*(\d{4})\b", re.I)
_RADEON_RE = re.compile(r"\bRadeon\s+(?:RX\s*)?(\d{4}[A-Z]*)\b", re.I)


def _load_profile_patterns() -> None:
    """Prefer the StoreProfile's spec_extraction_patterns (single source of vertical truth shared
    with seeding); the module literals above remain only as a profile-less fallback."""
    global _GPU_RE, _RADEON_RE, _VRAM_GB
    try:
        from src.app.platform.store_profile import profile_slot
        pat = profile_slot("spec_extraction_patterns", default=None)
        if isinstance(pat, dict):
            if pat.get("gpu_regex"):
                _GPU_RE = re.compile(str(pat["gpu_regex"]), re.I)
            if pat.get("radeon_regex"):
                _RADEON_RE = re.compile(str(pat["radeon_regex"]), re.I)
            if isinstance(pat.get("vram_gb_by_model"), dict):
                _VRAM_GB = {str(k): int(v) for k, v in pat["vram_gb_by_model"].items()}
    except Exception:
        pass


def extract_gpu(name: str):
    """(gpu_label, vram_gb|None) from a product name, or (None, None)."""
    m = _GPU_RE.search(name or "")
    if m:
        family, model = m.group(1).upper(), m.group(2)
        return f"GeForce {family} {model}", _VRAM_GB.get(model)
    m = _RADEON_RE.search(name or "")
    if m:
        return f"Radeon {m.group(1)}", None
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    from sqlalchemy import text
    from src.app.models.db import db_session

    _load_profile_patterns()
    changed = 0
    with db_session() as db:
        rows = db.execute(text("SELECT sku, name, specs FROM products WHERE active = 1")).fetchall()
        for sku, name, raw in rows:
            gpu, vram = extract_gpu(str(name or ""))
            if not gpu:
                continue
            try:
                specs = json.loads(raw) if raw else {}
                if not isinstance(specs, dict):
                    specs = {}
            except (json.JSONDecodeError, TypeError):
                specs = {}
            updates = {}
            if not specs.get("gpu"):
                updates["gpu"] = gpu
            if specs.get("gpu_discrete") is not True:
                updates["gpu_discrete"] = True
            if vram and not specs.get("gpu_vram_gb"):
                updates["gpu_vram_gb"] = vram
            if not updates:
                continue
            changed += 1
            print(f"{sku:16} {name[:58]:58} +{sorted(updates)}")
            if args.apply:
                specs.update(updates)
                db.execute(text("UPDATE products SET specs = :s WHERE sku = :k"),
                           {"s": json.dumps(specs), "k": sku})
        if args.apply:
            db.commit()
    print(f"\n{'APPLIED' if args.apply else 'DRY RUN'}: {changed} product(s) {'updated' if args.apply else 'would update'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
