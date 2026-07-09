"""Steam game-requirements connector (EDGE connector — NOT agnostic core). Phase W5.

Turns a game title into BOUNDED, citable evidence: the publisher's minimum/recommended
system requirements, structured for the fit layer and the narration claim guard. This is
Lane-3-adjacent evidence with provenance (source_url + retrieved_at), sitting between the
model's parametric knowledge and free web search.

Resolution order (fixture-first — CI must NEVER hit the network):
  1. Local curated fixture ``config/knowledge_pool/steam_fixtures.json`` (override with
     ``STEAM_FIXTURES_PATH``), keyed by normalized title with alias + token-subset fuzzy
     match ("cyberpunk" finds "Cyberpunk 2077"). Fixture hits return ``cached=True``.
  2. ONLY if ``allow_live=True`` AND the fixture missed: the official Steam storefront
     JSON endpoints (storesearch → appdetails), governed by the per-vertical
     ``external_research_allowlist`` (store.steampowered.com is enrolled for the
     electronics profile). 6s timeout, one retry, then give up. Live hits return
     ``cached=False`` and ``retrieved_at=None``.
On ANY failure the connector returns the fixture result or None — it never raises.

IMPORTANT domain knowledge — desktop vs laptop GPUs:
  Steam/publisher requirements name DESKTOP GPUs ("GTX 1060", "RTX 2060"). A laptop GPU
  with the same number is SLOWER than its desktop namesake (e.g. a laptop RTX 3060 is
  roughly a desktop RTX 2070; a desktop GTX 1060 needs a laptop RTX 3050/RTX 2050/
  GTX 1650 Ti-class part to match). This connector deliberately returns the RAW desktop
  GPU strings exactly as the publisher states them — the desktop→laptop translation
  happens in the fit layer via ``src/app/services/gpu_translation.py`` +
  ``config/knowledge_pool/gpu_translation.json``. Do NOT compare the returned ``gpu``
  strings against laptop GPU names directly.

Returned shape (both lanes):
  {"title", "appid", "minimum": {"ram_gb", "gpu", "storage_gb", "os"},
   "recommended": {same keys}, "tags": [...], "review_summary": str|None,
   "source": "steam" (fixtures may override, e.g. non-Steam titles like Fortnite carry
   "publisher"), "source_url", "retrieved_at", "cached": bool}
"""
from __future__ import annotations

import html as _html
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_FIXTURES_ENV = "STEAM_FIXTURES_PATH"
_DEFAULT_FIXTURES_PATH = os.path.join("config", "knowledge_pool", "steam_fixtures.json")

_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
_TIMEOUT_S = 6.0
_USER_AGENT = "ShopSquireResearch/0.1 (+governed web leg; requirements lookup)"

# Fixture cache with mtime-drift invalidation (same pattern as knowledge_pool.py).
_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_CACHE_META: Dict[str, Tuple[str, Optional[int], Optional[int]]] = {}


# ── fixture lane ─────────────────────────────────────────────────────────────
def _fixtures_path() -> str:
    return os.getenv(_FIXTURES_ENV) or _DEFAULT_FIXTURES_PATH


def _load_fixtures(force_reload: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Curated game entries, cached until the file's mtime/size drifts. None if absent."""
    try:
        path = _fixtures_path()
        if os.getenv("PYTEST_CURRENT_TEST"):  # tests may repoint the file; avoid order flakes
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
        if mtime_ns is None:
            _CACHE.pop("games", None)
            _CACHE_META.pop("games", None)
            return None
        meta = _CACHE_META.get("games")
        if not force_reload and "games" in _CACHE and meta == (path, mtime_ns, size):
            return _CACHE["games"]
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("games") if isinstance(data, dict) else data
        games = [g for g in raw if isinstance(g, dict) and g.get("title")] if isinstance(raw, list) else []
        if not games:
            return None
        _CACHE["games"] = games
        _CACHE_META["games"] = (path, mtime_ns, size)
        return games
    except Exception:
        return None


def _norm_title(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _lookup_fixture(title: str) -> Optional[Dict[str, Any]]:
    """Fuzzy title→entry: exact normalized match wins outright; else token-subset
    (query⊆title beats title⊆query) then plain substring containment. None on miss."""
    games = _load_fixtures()
    if not games:
        return None
    q = _norm_title(title)
    if not q:
        return None
    q_tokens = set(q.split())
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for game in games:
        names = [game.get("title")] + list(game.get("aliases") or [])
        for name in names:
            n = _norm_title(name)
            if not n:
                continue
            if n == q:
                return game
            n_tokens = set(n.split())
            score = 0.0
            if q_tokens and q_tokens <= n_tokens:
                score = 2.0 + len(q_tokens) / max(1, len(n_tokens))
            elif n_tokens and n_tokens <= q_tokens:
                score = 1.5 + len(n_tokens) / max(1, len(q_tokens))
            elif q in n or n in q:
                score = 1.0
            if score > best_score:
                best, best_score = game, score
    return best


def _norm_req(d: Any) -> Dict[str, Any]:
    d = d if isinstance(d, dict) else {}
    return {
        "ram_gb": d.get("ram_gb"),
        "gpu": d.get("gpu"),
        "storage_gb": d.get("storage_gb"),
        "os": d.get("os"),
    }


def _fixture_result(game: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": game.get("title"),
        "appid": game.get("appid"),
        "minimum": _norm_req(game.get("minimum")),
        "recommended": _norm_req(game.get("recommended")),
        "tags": list(game.get("tags") or []),
        "review_summary": game.get("review_summary"),
        "source": str(game.get("source") or "steam"),
        "source_url": game.get("source_url"),
        "retrieved_at": game.get("retrieved_at"),
        "cached": True,
    }


# ── requirements-HTML parsing (live lane) ────────────────────────────────────
_BREAK_RE = re.compile(r"(?i)<\s*(?:br|/li|/p|/ul|/div)\s*/?\s*>")
_TAG_RE = re.compile(r"<[^>]+>")
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(tb|gb|mb)", re.IGNORECASE)

_OS_LABELS = ("os", "operating system")
_GPU_LABELS = ("graphics", "video card", "video")
_STORAGE_LABELS = ("storage", "hard drive", "hard disk space", "available space")


def _html_to_lines(raw: Any) -> List[str]:
    text = _BREAK_RE.sub("\n", str(raw or ""))
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _parse_requirements_html(raw: Any) -> Dict[str, Any]:
    """Steam ``pc_requirements`` HTML → {"ram_gb", "gpu", "storage_gb", "os"}.

    Tags are stripped (list breaks become newlines) and each "Label: value" line is mapped
    by label. GPU strings are kept RAW (desktop names — see module docstring). Sizes accept
    GB/TB/MB; unknown fields stay None. Never raises."""
    out: Dict[str, Any] = {"ram_gb": None, "gpu": None, "storage_gb": None, "os": None}
    try:
        for line in _html_to_lines(raw):
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            lab = label.strip().lower().rstrip("*").strip()  # Steam uses "OS *:" footnotes
            val = value.strip()
            if not val:
                continue
            if out["os"] is None and lab in _OS_LABELS:
                out["os"] = val
            elif out["ram_gb"] is None and lab == "memory":
                m = _SIZE_RE.search(val)
                if m:
                    n, unit = float(m.group(1)), m.group(2).lower()
                    out["ram_gb"] = max(1, int(round(n / 1024))) if unit == "mb" else int(round(n))
            elif out["gpu"] is None and lab in _GPU_LABELS:
                out["gpu"] = val
            elif out["storage_gb"] is None and lab in _STORAGE_LABELS:
                m = _SIZE_RE.search(val)
                if m:
                    n, unit = float(m.group(1)), m.group(2).lower()
                    if unit == "tb":
                        out["storage_gb"] = int(round(n * 1024))
                    elif unit == "gb":
                        out["storage_gb"] = int(round(n))
                    else:
                        out["storage_gb"] = max(1, int(round(n / 1024)))
    except Exception:
        pass
    return out


# ── live lane (allow_live=True only) ─────────────────────────────────────────
def _get_json(client: Any, url: str, params: Dict[str, str]) -> Optional[Any]:
    """GET → parsed JSON with ONE retry; None after the second failure (no raise)."""
    for _attempt in (0, 1):
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.debug("steam fetch failed %s: %s", url, exc)
    return None


def _live_lookup(title: str) -> Optional[Dict[str, Any]]:
    """Official storefront JSON: storesearch resolves the appid, appdetails carries
    pc_requirements. Any failure at any step → None (fixture/None contract upstream)."""
    try:
        import httpx  # local import: the offline (fixture) lane must not require it

        with httpx.Client(
            timeout=_TIMEOUT_S,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            found = _get_json(client, _SEARCH_URL, {"term": str(title), "cc": "us", "l": "en"})
            items = (found or {}).get("items") or []
            appid = items[0].get("id") if items and isinstance(items[0], dict) else None
            if not appid:
                return None
            details = _get_json(client, _DETAILS_URL, {"appids": str(appid)})
            entry = (details or {}).get(str(appid)) or {}
            if not (isinstance(entry, dict) and entry.get("success")):
                return None
            data = entry.get("data") or {}
            pc = data.get("pc_requirements")
            if not isinstance(pc, dict):  # Steam returns [] when the section is absent
                pc = {}
            tags = [
                g.get("description")
                for g in (data.get("genres") or [])
                if isinstance(g, dict) and g.get("description")
            ]
            return {
                "title": data.get("name") or str(title),
                "appid": int(appid),
                "minimum": _parse_requirements_html(pc.get("minimum") or ""),
                "recommended": _parse_requirements_html(pc.get("recommended") or ""),
                "tags": tags,
                "review_summary": None,
                "source": "steam",
                "source_url": f"https://store.steampowered.com/app/{int(appid)}/",
                "retrieved_at": None,
                "cached": False,
            }
    except Exception as exc:
        logger.debug("steam live lookup failed for %r: %s", title, exc)
        return None


# ── public API ───────────────────────────────────────────────────────────────
def get_game_requirements(title: str, *, allow_live: bool = False) -> Optional[dict]:
    """Min/recommended system requirements for ``title`` as bounded, citable evidence.

    Fixture-first: the curated local cache always wins (CI never touches the network).
    The live storefront lane runs ONLY on a fixture miss AND ``allow_live=True`` (the
    caller is responsible for the consent gate / domain allowlist check). Returns None
    for unknown titles or on any failure — never raises.
    """
    try:
        if not _norm_title(title):
            return None
        fixture = _lookup_fixture(title)
        if fixture is not None:
            return _fixture_result(fixture)
        if not allow_live:
            return None
        return _live_lookup(title)
    except Exception as exc:
        logger.debug("get_game_requirements failed for %r: %s", title, exc)
        return None
