import json
import os


def default_headers() -> dict:
    return {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}


def write_feature_flags(flags: dict, path: str = os.path.join("config", "feature_flags.json")) -> None:
    """Merge test flags without depending on the archived V1 recommendation suite."""
    base = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
        if raw:
            try:
                base = json.loads(raw)
            except json.JSONDecodeError:
                base = {}
    merged = dict(base) if isinstance(base, dict) else {}
    merged.update(flags or {})
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, ensure_ascii=False, indent=2)
