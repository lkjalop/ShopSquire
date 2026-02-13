from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict


def append_worm_record(category: str, payload: Dict[str, Any]) -> None:
    try:
        record = {
            "time": datetime.utcnow().isoformat(),
            "category": category,
            "payload": payload,
        }
        with open("runs/audit_worm.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
