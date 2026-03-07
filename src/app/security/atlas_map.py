from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_CATALOG_PATH = Path("config/security/taxonomy/mitre_atlas_techniques.json")
_DEFAULT_TACTIC_BY_ID: Dict[str, str] = {
    "AML.T0043": "poison",
    "AML.T0020": "supply_chain",
    "AML.T0048": "exfiltration",
    "AML.T0015": "evasion",
}


@lru_cache(maxsize=1)
def _catalog() -> Dict[str, Dict[str, Any]]:
    try:
        raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def atlas_dimensions(mitre_ids: List[str] | None) -> Dict[str, Any]:
    ids = [str(x).strip() for x in (mitre_ids or []) if str(x).strip()]
    ids = list(dict.fromkeys(ids))
    cat = _catalog()
    enriched: List[Dict[str, Any]] = []
    tactics: List[str] = []
    for mid in ids:
        meta = cat.get(mid) or {}
        tactic = str(meta.get("tactic") or _DEFAULT_TACTIC_BY_ID.get(mid) or "unknown")
        tactics.append(tactic)
        enriched.append(
            {
                "id": mid,
                "name": str(meta.get("name") or ""),
                "tactic": tactic,
                "weight": float(meta.get("weight") or 0.0),
            }
        )
    return {
        "atlas_techniques": ids,
        "atlas_tactics": list(dict.fromkeys(tactics)),
        "atlas_enrichment": enriched,
    }


def enrich_security_event(event: Dict[str, Any] | None) -> Dict[str, Any]:
    out = dict(event or {})
    mitre_ids: List[str] = []
    try:
        if isinstance(out.get("mitre_atlas"), list):
            mitre_ids.extend([str(x) for x in out.get("mitre_atlas") or []])
    except Exception:
        pass
    details = out.get("details") if isinstance(out.get("details"), dict) else {}
    analysis = details.get("analysis") if isinstance(details.get("analysis"), dict) else {}
    if isinstance(analysis.get("mitre_atlas"), list):
        mitre_ids.extend([str(x) for x in analysis.get("mitre_atlas") or []])
    dim = atlas_dimensions(mitre_ids)
    out.update(dim)
    if details and analysis:
        analysis = dict(analysis)
        analysis.update(dim)
        details = dict(details)
        details["analysis"] = analysis
        out["details"] = details
    return out
