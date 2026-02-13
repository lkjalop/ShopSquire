from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Fetch a secret by name.

    Order of precedence:
    1) Environment variable `name`
    2) `config/secrets.json` key `name` (dev convenience only)
    """
    val = os.getenv(name)
    if val is not None:
        return val
    try:
        data = json.loads(Path("config/secrets.json").read_text())
        return data.get(name, default)
    except Exception:
        return default
