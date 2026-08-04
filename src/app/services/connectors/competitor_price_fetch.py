"""Competitor price fetcher (EDGE connector — NOT agnostic core).

Turns configured competitor product-page URLs into competitor_observation rows, feeding the existing
chain: observation → price_book join (market_signal_adapters 'competitor' source) →
detect_competitor_undercut → Market_Intelligence_Agent recommendation in the buyer's Decision Trace.

Design (deliberately conservative — David's "bad input quality produces bad autonomous behavior"):
  • per-SKU PRODUCT-PAGE URLs from config/competitor_sources.json — no search scraping, no discovery;
    the operator pastes the URLs they'd open in a browser (deterministic, low-volume, auditable);
  • robots.txt honoured at runtime (missing/404 robots → allowed, per the standard; a network error on
    robots → the domain is SKIPPED this run — conservative);
  • schema.org JSON-LD is the ONLY parse target (<script type="application/ld+json"> → @type Product →
    offers.price) — no brittle CSS selectors, no bs4 dependency;
  • the fetched page must MATCH our product (brand token + MPN/model or title-token overlap) before an
    observation is written — a wrong match is worse than no match, so below-threshold pages are skipped
    and counted, never recorded;
  • rate-limited (min_request_interval_sec between requests), identifying User-Agent, provenance label
    ``jsonld:<domain>`` on every row.

All I/O is injectable (fetch_fn / sleep_fn) so tests run fully offline on saved fixtures.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config/competitor_sources.json"

# MPN/model-code candidates in a product NAME. Ordered specific → generic; all uppercase-insensitive
# where vendors vary. Examples that must hit: "15-fc0433AU" (HP), "DC15255" (Dell), "14-he0013QU" (HP),
# "GS66-11UG" style dashes, bare 4-digit model in a series ("Inspiron 14 7440" → "7440").
_MPN_PATTERNS = (
    re.compile(r"\b\d{2}-[a-z]{2}\d{4}[A-Z]{2}\b"),          # HP: 15-fc0433AU
    re.compile(r"\b[A-Z]{2}\d{5}\b"),                        # Dell: DC15255
    re.compile(r"\b[A-Z0-9]{2,}-[A-Za-z0-9]{2,}\b"),         # generic dashed model codes
    re.compile(r"\b\d{4}[A-Z]{0,2}\b"),                      # bare model number: 7440
)
_STOP_TOKENS = {"laptop", "with", "inch", "intel", "core", "ryzen", "copilot", "windows", "full", "thin",
                "light", "gaming", "notebook", "touch", "screen"}


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as exc:
        logger.debug("competitor sources config unreadable (%s): %s", path, exc)
        return {}


# ── robots.txt (minimal, honest) ─────────────────────────────────────────────
def robots_allows(robots_txt: Optional[str], path: str, user_agent: str) -> bool:
    """Minimal robots.txt evaluation: rules under 'User-agent: *' or a group whose agent token appears in
    OUR UA. Disallow is prefix-match on the path; an empty Disallow allows everything. None (no robots /
    404) → allowed, per the standard."""
    if robots_txt is None:
        return True
    ua = user_agent.lower()
    applies = False
    disallows: List[str] = []
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = (p.strip() for p in line.split(":", 1))
        k = key.lower()
        if k == "user-agent":
            applies = val == "*" or (val and val.lower() in ua)
        elif k == "disallow" and applies:
            if val:
                disallows.append(val)
    return not any(path.startswith(d) for d in disallows)


# ── JSON-LD extraction ───────────────────────────────────────────────────────
_LDJSON_RE = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
                        re.IGNORECASE | re.DOTALL)


def extract_jsonld_products(html: str) -> List[Dict[str, Any]]:
    """All schema.org Product objects in the page's JSON-LD blocks (handles @graph and top-level lists).
    Malformed blocks are skipped, never raised."""
    out: List[Dict[str, Any]] = []
    for m in _LDJSON_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else (data.get("@graph") if isinstance(data, dict) and isinstance(data.get("@graph"), list) else [data])
        for node in nodes or []:
            if isinstance(node, dict) and str(node.get("@type") or "").lower() == "product":
                out.append(node)
    return out


def price_cents_from_product(node: Dict[str, Any]) -> Optional[int]:
    """offers.price (or lowPrice) → integer cents. Offers may be a dict or a list; price a number or
    string. None when absent/unparseable — the caller skips, never guesses."""
    offers = node.get("offers")
    cand: List[Any] = []
    for off in (offers if isinstance(offers, list) else [offers]):
        if isinstance(off, dict):
            cand.extend([off.get("price"), off.get("lowPrice")])
    for v in cand:
        if v is None:
            continue
        try:
            f = float(str(v).replace("$", "").replace(",", "").strip())
            if f > 0:
                return int(round(f * 100))
        except (ValueError, TypeError):
            continue
    return None


# ── product matching (the guard) ─────────────────────────────────────────────
def mpn_candidates(name: str) -> List[str]:
    seen: List[str] = []
    for pat in _MPN_PATTERNS:
        for m in pat.findall(name or ""):
            if m not in seen:
                seen.append(m)
    return seen


def _tokens(name: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", str(name or "").lower()) if t not in _STOP_TOKENS]


def matches_our_product(our_name: str, their_name: str) -> Tuple[bool, str]:
    """Does THEIR product page describe OUR product? Brand (first word) must match; then an exact
    MPN/model hit is decisive, else distinctive-token overlap >= 0.5. Returns (matched, reason)."""
    ours, theirs = str(our_name or ""), str(their_name or "")
    our_brand = (ours.split() or [""])[0].lower()
    if our_brand and our_brand not in theirs.lower():
        return False, f"brand '{our_brand}' absent"
    theirs_l = theirs.lower()
    for mpn in mpn_candidates(ours):
        if mpn.lower() in theirs_l:
            return True, f"mpn:{mpn}"
    our_toks = set(_tokens(ours))
    if not our_toks:
        return False, "no distinctive tokens"
    overlap = len(our_toks & set(_tokens(theirs))) / len(our_toks)
    if overlap >= 0.5:
        return True, f"tokens:{overlap:.2f}"
    return False, f"tokens:{overlap:.2f} < 0.5"


# ── the run ──────────────────────────────────────────────────────────────────
def _default_fetch(url: str, *, user_agent: str, timeout: float) -> Optional[str]:
    """GET a public page; None on any failure (a 404 robots.txt also returns None → 'allowed')."""
    try:
        import httpx
        r = httpx.get(url, headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True)
        return r.text if r.status_code == 200 else None
    except Exception as exc:
        logger.debug("fetch failed %s: %s", url, exc)
        raise ConnectionError(str(exc))


def fetch_and_record(db, *, config: Optional[Dict[str, Any]] = None,
                     fetch_fn: Optional[Callable[..., Optional[str]]] = None,
                     sleep_fn: Callable[[float], None] = time.sleep,
                     observed_at: str = "") -> Dict[str, Any]:
    """Fetch every configured (sku × retailer) product page and record validated observations.
    Returns {fetched, recorded, skipped_match, skipped_robots, skipped_no_price, errors}. Our product
    names are read from the products table for match validation."""
    from sqlalchemy import text as _sql
    from src.app.services.competitor_source import record_observation

    cfg = config if config is not None else load_config()
    out = {"fetched": 0, "recorded": 0, "skipped_match": 0, "skipped_robots": 0,
           "skipped_no_price": 0, "errors": 0}
    if not cfg or not cfg.get("enabled"):
        out["disabled"] = True
        return out
    ua = str(cfg.get("user_agent") or "ShopSquireDemo/0.1")
    interval = float(cfg.get("min_request_interval_sec") or 2.5)
    timeout = float(cfg.get("timeout_sec") or 10)
    fetch = fetch_fn or (lambda url: _default_fetch(url, user_agent=ua, timeout=timeout))

    robots_cache: Dict[str, Optional[str]] = {}
    first_request = True
    for sku, per_retailer in (cfg.get("product_urls") or {}).items():
        row = db.execute(_sql("SELECT name FROM products WHERE sku=:s"), {"s": str(sku)}).fetchone()
        our_name = str(row[0]) if row and row[0] else ""
        for domain, url in (per_retailer or {}).items():
            url = str(url or "").strip()
            if not url or not our_name:
                continue
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            if not first_request:
                sleep_fn(interval)
            first_request = False
            # robots: fetch once per domain; network error → conservative skip of the whole domain
            if base not in robots_cache:
                try:
                    robots_cache[base] = fetch(f"{base}/robots.txt")
                except ConnectionError:
                    robots_cache[base] = "__unreachable__"
            robots = robots_cache[base]
            if robots == "__unreachable__" or not robots_allows(
                    None if robots is None else str(robots), parsed.path, ua):
                out["skipped_robots"] += 1
                continue
            try:
                html = fetch(url)
            except ConnectionError:
                out["errors"] += 1
                continue
            if not html:
                out["errors"] += 1
                continue
            out["fetched"] += 1
            recorded_here = False
            for node in extract_jsonld_products(html):
                ok, reason = matches_our_product(our_name, str(node.get("name") or ""))
                if not ok:
                    continue
                cents = price_cents_from_product(node)
                if cents is None:
                    out["skipped_no_price"] += 1
                    break
                record_observation(db, sku=str(sku), competitor_price_cents=cents,
                                   competitor=str(domain), observed_at=observed_at,
                                   source=f"jsonld:{domain}")
                logger.info("competitor price %s @ %s = %sc (%s)", sku, domain, cents, reason)
                out["recorded"] += 1
                recorded_here = True
                break   # one observation per (sku, retailer) per run
            if not recorded_here and html:
                # page fetched but no matching product → count once (guard refused to guess)
                if not any(matches_our_product(our_name, str(n.get("name") or ""))[0]
                           for n in extract_jsonld_products(html)):
                    out["skipped_match"] += 1
    try:
        db.commit()
    except Exception as exc:
        logger.debug("competitor fetch commit failed: %s", exc)
    return out
