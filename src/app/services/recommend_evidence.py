"""Per-pick structured EVIDENCE for grounded narration (agnostic CORE).

The narrator must justify picks from evidence, not vibes. This derives a small, typed evidence record per
candidate — price_fit, inventory_fit, fleet_fit, office_fit, portability, docking, warranty, os_ecosystem,
risk_penalties — from data the candidate already carries (price / stock / factors) plus profile MARKER
groups (so the only vertical vocabulary lives in the StoreProfile). It also renders a compact prompt block
the LLM narrates over, and an answer-level summary so callers can assert "don't claim best-for-work when no
office-grade pick qualified".

Each metric is {status, detail}. Vertical-blind (markers come from marker_fn); never raises.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

_METRIC_KEYS = ("price_fit", "inventory_fit", "fleet_fit", "office_fit", "portability",
                "docking", "warranty", "os_ecosystem", "risk_penalties")


def _haystack(p: Dict[str, Any]) -> str:
    try:
        specs = json.dumps(p.get("specs") or {}, ensure_ascii=False)
    except Exception:
        specs = ""
    feats = " ".join(str(x) for x in (p.get("features") or []))
    return f"{p.get('name') or ''} {specs} {feats}".lower()


def _price(p: Dict[str, Any]) -> Optional[float]:
    for k in ("price", "price_cents"):
        v = p.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v) / 100.0 if k == "price_cents" else float(v)
    return None


def _markers(marker_fn: Optional[Callable], group: str) -> List[str]:
    if marker_fn is None:
        return []
    try:
        return [str(m).strip().lower() for m in (marker_fn(group) or []) if str(m).strip()]
    except Exception:
        return []


def _hit(hay: str, markers: List[str]) -> bool:
    return any(m in hay for m in markers)


def build_pick_evidence(
    product: Dict[str, Any],
    *,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    marker_fn: Optional[Callable] = None,
) -> Dict[str, Dict[str, Any]]:
    """Typed evidence for ONE candidate. Each value is {status, detail}; status is a short enum-ish token
    the narrator can render. Marker-based metrics (fleet/office/portability/docking/warranty/os) read the
    profile via marker_fn(group) — no vocabulary here."""
    hay = _haystack(product)
    ev: Dict[str, Dict[str, Any]] = {}

    # price_fit — within / under / over the stated budget (no budget → unknown)
    price = _price(product)
    if price is None:
        ev["price_fit"] = {"status": "unknown", "detail": "no price"}
    elif budget_max is not None and price > float(budget_max):
        ev["price_fit"] = {"status": "over", "detail": f"${price:,.0f} > ${float(budget_max):,.0f} budget"}
    elif budget_min is not None and price < float(budget_min):
        ev["price_fit"] = {"status": "under", "detail": f"${price:,.0f} < ${float(budget_min):,.0f} floor"}
    elif budget_min is not None or budget_max is not None:
        ev["price_fit"] = {"status": "within", "detail": f"${price:,.0f} within budget"}
    else:
        ev["price_fit"] = {"status": "unknown", "detail": f"${price:,.0f} (no budget given)"}

    # inventory_fit — from the finalizer's stock honesty fields
    ss = str(product.get("stock_status") or "").strip().lower()
    lvl = product.get("stock_level")
    if ss in ("in_stock", "low_stock", "very_low_stock"):
        ev["inventory_fit"] = {"status": ss, "detail": (f"{lvl} in stock" if isinstance(lvl, (int, float)) else ss.replace("_", " "))}
    elif ss == "out_of_stock":
        ev["inventory_fit"] = {"status": "out_of_stock", "detail": "out of stock"}
    elif isinstance(lvl, (int, float)):
        ev["inventory_fit"] = {"status": "in_stock" if lvl > 0 else "out_of_stock", "detail": f"{int(lvl)} in stock"}
    else:
        ev["inventory_fit"] = {"status": "unknown", "detail": "stock not reported"}

    # marker-based suitability (profile-sourced groups)
    biz = _hit(hay, _markers(marker_fn, "business_class")) or _hit(hay, _markers(marker_fn, "productivity_grade"))
    fleet = _hit(hay, _markers(marker_fn, "office_fleet"))
    ev["office_fit"] = {"status": "office_grade" if biz else "consumer", "detail": "business-line build" if biz else "consumer build"}
    ev["fleet_fit"] = {"status": "managed" if fleet else "unmanaged", "detail": "vPro/TPM/docking/warranty markers" if fleet else "no fleet-management markers"}
    ev["portability"] = {"status": "portable" if _hit(hay, _markers(marker_fn, "portability")) else "standard",
                         "detail": "thin/light markers" if _hit(hay, _markers(marker_fn, "portability")) else "standard chassis"}
    ev["docking"] = {"status": "yes" if _hit(hay, _markers(marker_fn, "docking")) else "no",
                     "detail": "docking/Thunderbolt" if _hit(hay, _markers(marker_fn, "docking")) else "none stated"}
    ev["warranty"] = {"status": "extended" if _hit(hay, _markers(marker_fn, "warranty")) else "standard",
                      "detail": "onsite/NBD warranty markers" if _hit(hay, _markers(marker_fn, "warranty")) else "standard warranty"}

    # os_ecosystem — first matching os marker group wins; else "windows" default group, else unknown
    os_label = "unknown"
    for group, label in (("os_macos", "macOS"), ("os_chromeos", "ChromeOS"), ("os_windows", "Windows")):
        if _hit(hay, _markers(marker_fn, group)):
            os_label = label
            break
    ev["os_ecosystem"] = {"status": os_label, "detail": f"{os_label} ecosystem" if os_label != "unknown" else "OS not detected"}

    # risk_penalties — negative scoring factors / exclusions already attached to the candidate
    factors = product.get("factors") if isinstance(product.get("factors"), dict) else {}
    negs = [str(x).lstrip("-") for x in (factors.get("negative") or [])][:4]
    excl = [str(x) for x in (product.get("exclusions") or [])][:4]
    risks = negs + [f"exclusion:{e}" for e in excl]
    ev["risk_penalties"] = {"status": "present" if risks else "none", "detail": ", ".join(risks) if risks else "no penalties"}

    return ev


def summarize_answer_evidence(
    results: List[Dict[str, Any]],
    *,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    use_case: Optional[str] = None,
    marker_fn: Optional[Callable] = None,
    top_n: int = 4,
) -> Dict[str, Any]:
    """Answer-level evidence: per-pick metrics for the top picks + aggregate flags. ``office_grade_count``
    and ``work_suitable`` let a caller refuse a 'best for work' claim when nothing office-grade qualified."""
    picks = []
    office_grade = 0
    for p in (results or [])[:top_n]:
        if not isinstance(p, dict):
            continue
        ev = build_pick_evidence(p, budget_min=budget_min, budget_max=budget_max, marker_fn=marker_fn)
        if ev["office_fit"]["status"] == "office_grade":
            office_grade += 1
        picks.append({"sku": str(p.get("sku") or ""), "name": str(p.get("name") or ""), "evidence": ev})
    is_work = str(use_case or "").strip().lower() in ("office", "business", "corporate", "work")
    return {
        "use_case": use_case,
        "picks": picks,
        "office_grade_count": office_grade,
        # only TRUE when this is a work query AND at least one pick is genuinely office-grade
        "work_suitable": bool(is_work and office_grade > 0),
    }


def render_evidence_block(answer_evidence: Dict[str, Any]) -> str:
    """Compact prompt block the narrator must ground on. Names each pick with its key metrics, and states
    explicitly when NO office-grade pick qualified (so the LLM won't claim 'best for work')."""
    picks = (answer_evidence or {}).get("picks") or []
    if not picks:
        return ""
    lines = ["Per-pick evidence (narrate from this; do not invent specs):"]
    for p in picks[:4]:
        ev = p.get("evidence") or {}
        parts = []
        for k in ("price_fit", "office_fit", "fleet_fit", "inventory_fit", "portability", "os_ecosystem"):
            cell = ev.get(k) or {}
            if cell.get("status") and cell.get("status") not in ("unknown",):
                parts.append(f"{k}={cell['status']}")
        rp = (ev.get("risk_penalties") or {})
        if rp.get("status") == "present":
            parts.append(f"risk={rp.get('detail')}")
        lines.append(f"- {p.get('name') or p.get('sku')}: " + ", ".join(parts))
    if answer_evidence.get("use_case") in ("office", "business", "corporate", "work") and not answer_evidence.get("work_suitable"):
        lines.append("- NOTE: no office-grade pick qualified — do NOT claim any item is 'best for work'; "
                     "suggest sourcing/procurement of business-class units instead.")
    return "\n".join(lines)
