"""Challenge-defense justification (N4, 2026-07-07) — agnostic core.

When a buyer CHALLENGES a recommendation ("are you sure?", "why would that be good for X?"), the
platform previously re-ran the pipeline and re-pasted the same pitch (screenshot-26's second half).
This module builds a DEFEND-OR-CONCEDE answer instead: the top pick's structured specs are compared
against the use-case KB's required_specs, requirement by requirement, and the verdict admits gaps
honestly — "meets the minimum, not the recommended tier" converts a skeptic; boilerplate loses them.

Vertical-blind: the mechanism walks ``<field>_min`` keys in the KB entry and reads ``specs[<field>]``
off the product — every WORD (use-case names, spec fields, requirement text) comes from
config/use_case_kb.json + the product row (DATA). Pure; never raises; '' when not a challenge turn.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_CHALLENGE_RE = re.compile(
    r"\bare\s+you\s+sure\b|\bwhy\s+would\b|\bhow\s+do\s+you\s+know\b|\bprove\s+it\b|"
    r"\bis\s+that\s+(?:right|correct)\b|\breally\s+(?:good|enough|suitable)\b|\bjustify\b|"
    r"\bconvince\s+me\b|\byou\s+sure\b|\bdoubt\b", re.I)


def is_challenge_turn(query: str) -> bool:
    return bool(_CHALLENGE_RE.search(str(query or "")))


def _resolve_kb_entry(use_case: str, kb: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """use-case id → KB entry: direct key → alias table → token-overlap fuzzy (profile ids and KB keys
    drifted apart historically, e.g. ml_ai vs ai_ml_workstation — overlap on {ai, ml} binds them)."""
    key = str(use_case or "").strip().lower()
    if not key:
        return None, None
    cases = kb.get("use_cases") if isinstance(kb.get("use_cases"), dict) else {}
    if key in cases:
        return key, cases[key]
    aliases = kb.get("use_case_aliases") if isinstance(kb.get("use_case_aliases"), dict) else {}
    ali = str(aliases.get(key) or aliases.get(key.replace("_", " ")) or "")
    if ali and ali in cases:
        return ali, cases[ali]
    toks = {t for t in key.replace("-", "_").split("_") if len(t) >= 2}
    best, best_n = None, 0
    for k in cases:
        overlap = len(toks & {t for t in k.split("_") if len(t) >= 2})
        if overlap > best_n:
            best, best_n = k, overlap
    if best and best_n >= 1:
        return best, cases[best]
    return None, None


def _pretty_field(field: str) -> str:
    return field.replace("_", " ").strip()


def build_challenge_justification(query: str, results: List[dict], constraints: Dict[str, Any]) -> str:
    """Spec-vs-requirement defense for a challenged pick. '' unless (challenge turn AND a top result
    AND a resolvable KB entry with required_specs) — callers fall through to their normal answer."""
    if not is_challenge_turn(query):
        return ""
    top = results[0] if results and isinstance(results[0], dict) else None
    if not top:
        return ""
    use_case = str((constraints or {}).get("use_case") or "").strip()
    if not use_case:
        return ""
    try:
        from src.app.services.recommend_budget_parsing import load_capability_kb
        kb = load_capability_kb() or {}
    except Exception:
        return ""
    kb_key, entry = _resolve_kb_entry(use_case, kb)
    if not entry or not isinstance(entry.get("required_specs"), dict):
        return ""

    specs = top.get("specs") if isinstance(top.get("specs"), dict) else {}
    name = str(top.get("name") or "this pick").strip()
    label = str(entry.get("label") or kb_key or use_case).strip()

    met: List[str] = []
    gaps: List[str] = []
    unknown: List[str] = []
    for req_key, req_val in entry["required_specs"].items():
        if not str(req_key).endswith("_min"):
            continue   # only numeric floors are mechanically checkable here
        field = str(req_key)[:-4]
        try:
            need = float(req_val)
        except (TypeError, ValueError):
            continue
        raw = specs.get(field)
        try:
            have = float(raw)
        except (TypeError, ValueError):
            unknown.append(f"{_pretty_field(field)} (not recorded for this product)")
            continue
        line = f"{_pretty_field(field)}: {int(have) if have == int(have) else have} vs {int(need) if need == int(need) else need} minimum"
        (met if have >= need else gaps).append(line)

    if not met and not gaps and not unknown:
        return ""

    parts = [f"Fair challenge — here's the {name} against the {label} requirements:"]
    if met:
        parts.append("meets — " + "; ".join(met[:4]) + ".")
    if gaps:
        parts.append("falls short — " + "; ".join(gaps[:4]) + ".")
    if unknown:
        parts.append("unverified — " + "; ".join(unknown[:3]) + ".")
    if gaps:
        parts.append("Honest verdict: it clears some bars but not all — if those gaps matter for your "
                     "workload, I'd step up a tier or I can show alternatives that clear every minimum.")
    elif unknown:
        parts.append("Verdict: everything I can verify checks out; the unverified specs are worth "
                     "confirming before you commit.")
    else:
        parts.append("Verdict: it clears every stated minimum for this use case.")
    soft = entry.get("soft_requirements")
    if isinstance(soft, list) and soft:
        parts.append(f"(Guide: {str(soft[0])})")
    return " ".join(parts)
