"""Catalog-backed brand guards with transaction-local advisory probes."""
import logging
import re as _re
from typing import Any, Optional

logger = logging.getLogger("shopsquire.recommendation_core.turn_router")


def _clamp_brand(db, raw: Any) -> Optional[str]:
    """Model-named brand → the CATALOG's canonical casing, or None. The clamp is the catalog
    itself (distinct non-null brands) — an invented/unstocked brand is dropped, never guessed."""
    b = str(raw or "").strip().lower()
    if not b or db is None:
        return None
    try:
        from sqlalchemy import text as _t
        # These are advisory clamps. A schema/read failure must roll back only
        # this probe; otherwise PostgreSQL marks the request transaction failed
        # and every later authoritative taxonomy read also fails.
        with db.begin_nested():
            rows = db.execute(_t("SELECT DISTINCT brand FROM products "
                                 "WHERE brand IS NOT NULL AND brand != ''")).fetchall()
        for (name,) in rows:
            if str(name).strip().lower() == b:
                return str(name)
    except Exception as exc:
        logger.debug("brand clamp lookup failed: %s", repr(exc)[:100])
    return None


def _explicitly_excluded_brand(db, query: str) -> Optional[str]:
    """Return a catalog brand named in an explicit exclusion phrase.

    The model owns semantic interpretation, but a clamped positive brand may not
    contradict an unambiguous buyer negation.  The vocabulary comes from the
    tenant catalog; this guard contains no merchant or vertical brand list.
    """
    q = " ".join(str(query or "").strip().lower().split())
    if not q or db is None:
        return None
    try:
        from sqlalchemy import text as _t
        with db.begin_nested():
            rows = db.execute(_t(
                "SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != ''"
            )).fetchall()
    except Exception as exc:
        logger.debug("brand exclusion lookup failed: %s", repr(exc)[:100])
        return None
    for (name,) in rows:
        canonical = str(name or "").strip()
        if not canonical:
            continue
        brand = _re.escape(canonical.lower())
        patterns = (
            rf"\b(?:no|not|except|excluding|exclude|without)\s+{brand}\b",
            rf"\b(?:no|nothing)\s+from\s+{brand}\b",
            rf"\banything\s+but\s+{brand}\b",
        )
        if any(_re.search(pattern, q) for pattern in patterns):
            return canonical
    return None
