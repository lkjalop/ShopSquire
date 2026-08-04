"""Workload fit verdicts (W2/W4, 2026-07-08) — compare requirement floors against catalog
products and KEEP the comparison: meets_minimum / meets_recommended / missing / why. This is
the "stop losing the evidence" artifact — the verdicts ride the response payload, the
narration preamble, AND the guard evidence, so the narrator can finally cite the numbers the
platform actually computed instead of drafting its own (which the claim guard then rejects).

Agnostic core: reads only numeric spec fields; entity vocabulary comes from the workload
stage / use-case KB. Never raises."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _specs_dict(product: Dict[str, Any]) -> Dict[str, Any]:
    """Candidates carry specs as raw JSON strings from the DB row; results carry dicts —
    normalize once (live failure: AttributeError 'str' has no .get)."""
    specs = product.get("specs")
    if isinstance(specs, dict):
        return specs
    if isinstance(specs, str) and specs.strip().startswith("{"):
        try:
            out = json.loads(specs)
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    return {}


def _spec_value(product: Dict[str, Any], *keys: str) -> Optional[float]:
    specs = _specs_dict(product)
    for k in keys:
        v = specs.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            m = _NUM_RE.search(str(v))
            if m:
                return float(m.group(1))
    return None


def fit_verdicts(floors: Dict[str, Any], products: List[Dict[str, Any]], *, top_n: int = 5) -> List[Dict[str, Any]]:
    """Per-product verdicts against merged requirement floors. Empty floors -> []."""
    if not floors or not products:
        return []
    out: List[Dict[str, Any]] = []
    for p in products[:top_n]:
        if not isinstance(p, dict):
            continue
        ram = _spec_value(p, "ram_gb", "ram")
        vram = _spec_value(p, "gpu_vram_gb", "vram_gb", "vram")
        why_fit: List[str] = []
        why_not: List[str] = []
        missing: List[str] = []
        meets_min = True
        meets_rec = True

        def _check(val: Optional[float], min_key: str, rec_key: str, label: str, unit: str) -> None:
            nonlocal meets_min, meets_rec
            mn, rc = floors.get(min_key), floors.get(rec_key)
            if val is None:
                if mn or rc:
                    missing.append(label)
                    meets_rec = False
                return
            if mn:
                if val >= float(mn):
                    why_fit.append(f"{label} {val:g}{unit} meets the {float(mn):g}{unit} minimum")
                else:
                    meets_min = False
                    why_not.append(f"{label} {val:g}{unit} is below the {float(mn):g}{unit} minimum")
            if rc:
                if val >= float(rc):
                    why_fit.append(f"{label} {val:g}{unit} meets the {float(rc):g}{unit} recommended")
                else:
                    meets_rec = False
                    why_not.append(f"{label} {val:g}{unit} is below the {float(rc):g}{unit} recommended")

        _check(ram, "min_ram_gb", "recommended_ram_gb", "RAM", "GB")
        _check(vram, "min_gpu_vram_gb", "recommended_gpu_vram_gb", "GPU memory", "GB")
        if floors.get("gpu_needed") and vram is None:
            gpu_txt = str(_specs_dict(p).get("gpu") or "")
            if not gpu_txt or "integrated" in gpu_txt.lower():
                meets_min = False
                why_not.append("needs a discrete GPU")
        out.append({
            "sku": p.get("sku"), "name": (p.get("name") or "")[:80],
            "meets_minimum": meets_min, "meets_recommended": meets_rec and meets_min,
            "missing_specs": missing, "why_fit": why_fit[:4], "why_not_fit": why_not[:4],
        })
    return out


def fit_evidence_note(entities: List[str], floors: Dict[str, Any], verdicts: List[Dict[str, Any]]) -> Optional[str]:
    """Compact platform-authored note for the narration preamble + guard evidence: the
    requirement numbers and per-product verdicts the narrator may cite."""
    if not floors or not verdicts:
        return None
    lines = []
    ent = ", ".join(entities[:4]) if entities else "this workload"
    req_bits = []
    for key, label in (("min_ram_gb", "min RAM"), ("recommended_ram_gb", "recommended RAM"),
                       ("min_gpu_vram_gb", "min GPU memory"), ("recommended_gpu_vram_gb", "recommended GPU memory")):
        if floors.get(key):
            req_bits.append(f"{label} {float(floors[key]):g}GB")
    lines.append(f"WORKLOAD FIT FACTS for {ent} ({'; '.join(req_bits)}):" if req_bits
                 else f"WORKLOAD FIT FACTS for {ent}:")
    for v in verdicts[:4]:
        verdict = ("meets recommended" if v["meets_recommended"]
                   else "meets minimum only" if v["meets_minimum"] else "below minimum")
        detail = "; ".join((v["why_not_fit"] or v["why_fit"])[:2])
        lines.append(f"- {v['name']}: {verdict}" + (f" ({detail})" if detail else ""))
    return "\n".join(lines)
