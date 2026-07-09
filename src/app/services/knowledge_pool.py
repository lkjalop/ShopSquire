"""Knowledge pool — platform-CURATED domain facts the narrator may cite (agnostic core).

Why this exists (model A/B rounds 3-4, 2026-07-08): the narration claim guard
(product_claim_guard) rightly rejects prose citing facts absent from evidence — but models
keep making TRUE domain claims ("sustained LLM training wants 16GB+ VRAM", "a datacenter
card carries 40-80GB") that no product row states, so honest expertise was being suppressed
along with hallucination. The fix is a third evidence lane: this module is Lane-3 of the
information-gathering ladder in docs/AGENTIC_ORCHESTRATOR_ARCHITECTURE_2026-07-08.md §2 —
it sits BETWEEN the model's parametric knowledge (unverifiable, guard-hostile) and live web
search (volatile, consent-gated). Because every statement here is platform-authored, reviewed,
and versioned in config, the note it emits is LEGITIMATE guard evidence: the guard can verify
the narrator's numeric claims against this exact text, and the narrator is told to cite
freely but never extrapolate beyond it.

Demarcation: pure DATA→NOTE assembly (deterministic, <1ms, no LLM, no I/O beyond one cached
JSON read). WHICH facts exist is vertical flavour → config/knowledge_pool/{profile_id}.json;
HOW they are selected and formatted is the agnostic mechanism below. A vertical with no pool
file emits None — silence, not filler (same contract as capability_registry).

Fail-safe contract: never raises. Missing/malformed file → None. Cache reloads on file mtime
drift (same pattern as feature_flags.get_flags) and force-reloads under PYTEST_CURRENT_TEST
so tests that rewrite the pool are never order-dependent.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_POOL_DIR_ENV = "KNOWLEDGE_POOL_DIR"
_DEFAULT_POOL_DIR = "config/knowledge_pool"
_HEADER = (
    "DOMAIN KNOWLEDGE (platform-curated — cite freely, "
    "do not extrapolate beyond these statements):"
)

# Per-profile cache: pid -> entries; meta: pid -> (path, mtime_ns, size) for drift detection.
_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_CACHE_META: Dict[str, Tuple[str, Optional[int], Optional[int]]] = {}


def _resolve_profile_id(profile_id: Optional[str]) -> str:
    """Explicit arg → active vertical (ContextVar → STORE_PROFILE_ID env → electronics)."""
    if profile_id and str(profile_id).strip():
        return str(profile_id).strip()
    try:
        from src.app.platform.store_profile import active_profile_id
        return active_profile_id()
    except Exception:
        return (os.getenv("STORE_PROFILE_ID") or "electronics").strip() or "electronics"


def _read_entries(path: str) -> Optional[List[Dict[str, Any]]]:
    """Parse the pool file; accept {"entries": [...]} or a bare list. None on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("entries") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return None
        entries = [
            e for e in raw
            if isinstance(e, dict) and e.get("id") and e.get("statement")
        ]
        return entries or None
    except Exception:
        return None


def load_pool(profile_id: Optional[str] = None, force_reload: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Entries for the vertical's pool, cached with mtime-drift invalidation. None if absent."""
    try:
        pid = _resolve_profile_id(profile_id)
        path = os.path.join(os.getenv(_POOL_DIR_ENV) or _DEFAULT_POOL_DIR, f"{pid}.json")
        if os.getenv("PYTEST_CURRENT_TEST"):  # tests rewrite pool files; avoid order flakes
            force_reload = True
        mtime_ns: Optional[int] = None
        size: Optional[int] = None
        try:
            if os.path.exists(path):
                st = os.stat(path)
                mtime_ns = getattr(st, "st_mtime_ns", None) or int(st.st_mtime * 1_000_000_000)
                size = st.st_size
        except Exception:
            pass
        if mtime_ns is None:  # file missing/unreadable → silence, and drop any stale cache
            _CACHE.pop(pid, None)
            _CACHE_META.pop(pid, None)
            return None
        meta = _CACHE_META.get(pid)
        if not force_reload and pid in _CACHE and meta == (path, mtime_ns, size):
            return _CACHE[pid]
        entries = _read_entries(path)
        if entries is None:
            _CACHE.pop(pid, None)
            _CACHE_META.pop(pid, None)
            return None
        _CACHE[pid] = entries
        _CACHE_META[pid] = (path, mtime_ns, size)
        return entries
    except Exception:
        return None


def _keyword_hit(keyword: str, query_lc: str) -> bool:
    """Word-anchored match: exact word always; stem-prefix only for keywords >=4 chars so
    'train' finds 'training' but 'ram' can never fire inside 'program'."""
    kw = str(keyword or "").strip().lower()
    if not kw:
        return False
    if re.search(r"\b" + re.escape(kw) + r"\b", query_lc):
        return True
    return len(kw) >= 4 and re.search(r"\b" + re.escape(kw), query_lc) is not None


def _topic_matches(topic: str, use_case: Optional[str]) -> bool:
    """Loose slug match: containment either way, or any shared underscore-token
    (use_case 'ai_ml' ↔ topic 'ai_training')."""
    if not topic or not use_case:
        return False
    t, u = str(topic).strip().lower(), str(use_case).strip().lower()
    if not t or not u:
        return False
    if t in u or u in t:
        return True
    return bool(set(t.split("_")) & set(u.split("_")))


def knowledge_note(
    query: str,
    use_case: Optional[str] = None,
    profile_id: Optional[str] = None,
    max_entries: int = 4,
) -> Optional[str]:
    """Top-scoring curated statements relevant to THIS query, as a citable preamble note.

    Scoring: +1 per keyword found in the query, +2 when the entry topic loosely matches the
    resolved use-case slug. Only entries with score > 0 qualify; ties keep file order so
    curators control priority. Returns None when nothing scores — silence, not filler.
    Each line carries a [kp:<id>] citation so narration provenance is auditable.
    """
    try:
        if not (query or "").strip():
            return None
        entries = load_pool(profile_id=profile_id)
        if not entries:
            return None
        q = query.lower()
        scored: List[Tuple[int, int, Dict[str, Any]]] = []
        for idx, entry in enumerate(entries):
            try:
                keywords = entry.get("keywords") or []
                score = sum(1 for kw in keywords if _keyword_hit(kw, q))
                if _topic_matches(str(entry.get("topic") or ""), use_case):
                    score += 2
                if score > 0:
                    scored.append((score, idx, entry))
            except Exception:
                continue  # one malformed entry must never sink the whole note
        if not scored:
            return None
        scored.sort(key=lambda t: (-t[0], t[1]))
        top = scored[: max(1, int(max_entries))]
        lines = [f"- {e['statement']} [kp:{e['id']}]" for _, _, e in top]
        return _HEADER + "\n" + "\n".join(lines)
    except Exception:
        return None
