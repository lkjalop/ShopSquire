"""Inventory query service — safe direct DB lookups for stock-level queries.

This module is the ONLY authorised path for surfacing stock counts to users.
The LLM must NEVER generate stock counts — it hallucinates. All stock data
returned to users must pass through _get_stock_level() or batch_stock_levels().

Security properties:
- INVENTORY_INJECTION_RE guards against prompt-injection attempts in the query
  string before any stock lookup or LLM call.
- Stock counts come from the inventory table, never from LLM output.
- is_inventory_query() short-circuits the full recommendation pipeline so an
  injection attempt in a stock query cannot influence product ranking.
"""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as _text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.inventory_query")

# ── Injection guard ───────────────────────────────────────────────────────────

INVENTORY_INJECTION_RE = re.compile(
    r"\b("
    r"ignore\s+(all\s+)?instructions?|always\s+in\s+stock|unlimited\s+stock|"
    r"set\s+stock|update\s+(the\s+)?inventory|mark\s+as\s+available|"
    r"bypass\s+stock\s+check|override\s+stock|system\s+prompt|"
    r"developer\s+mode|ignore\s+policy|admin\s+override"
    r")\b",
    re.IGNORECASE,
)

# ── Stock query NLP intent detection ─────────────────────────────────────────

STOCK_QUERY_RE = re.compile(
    r"\b("
    r"in\s+stock|out\s+of\s+stock|how\s+many(\s+are|\s+left|\s+remaining|\s+available)?|"
    r"available(\s+now|\s+today)?|units?\s+(left|remaining|available)|"
    r"when\s+(will|is)\s+.{1,30}(back|available|in\s+stock)|"
    # NOTE: a bare "can i get/buy/order X" is PURCHASE intent, not a stock question — it used to live here
    # and hijacked shopping asks ("can i get help with 15 work laptops…") into the inventory lane, which
    # then answered "name the specific product" with zero results. Stock-flavoured phrasings are still
    # caught by the explicit alternatives around it.
    r"stock\s+level|inventory|"
    r"(do\s+you\s+have|have\s+you\s+got|is\s+there)\s+.{1,30}(in\s+stock|available)"
    r")\b",
    re.IGNORECASE,
)


def is_inventory_query(query: str) -> bool:
    """Return True when the query is primarily asking about stock availability."""
    return bool(STOCK_QUERY_RE.search(query or ""))


def has_injection_attempt(query: str) -> bool:
    """Return True when the query contains inventory-specific injection patterns."""
    return bool(INVENTORY_INJECTION_RE.search(query or ""))


# ── SKU extraction ────────────────────────────────────────────────────────────

_SKU_RE = re.compile(r"\b([A-Z0-9][-A-Z0-9]{3,20})\b")


def extract_possible_skus(query: str) -> List[str]:
    """Heuristic: extract token sequences that look like SKU codes."""
    return list(dict.fromkeys(_SKU_RE.findall((query or "").upper())))


def fuzzy_sku_lookup(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Find products whose name or SKU approximately matches *query*.

    Returns a list of dicts: {sku, name, brand}.  Safe: uses parameterised SQL.
    """
    term = f"%{str(query or '').strip()[:80]}%"
    try:
        with db_session() as db:
            rows = db.execute(
                _text(
                    "SELECT sku, name, brand FROM products "
                    "WHERE (LOWER(name) LIKE LOWER(:t) OR LOWER(sku) LIKE LOWER(:t)) "
                    "AND active IS NOT FALSE LIMIT :lim"
                ),
                {"t": term, "lim": int(limit)},
            ).fetchall()
        return [{"sku": r[0], "name": r[1], "brand": r[2]} for r in rows]
    except Exception as exc:
        logger.debug("fuzzy_sku_lookup failed: %s", exc)
        return []


# ── Stock level helpers ───────────────────────────────────────────────────────

def get_stock_level(sku: str) -> int:
    """Return total stock across all warehouses for *sku*. Returns 0 on error.

    Joins through products because inventory.product_id references products.id;
    the inventory table has no sku column.
    """
    try:
        with db_session() as db:
            row = db.execute(
                _text(
                    "SELECT COALESCE(SUM(i.stock), 0) "
                    "FROM inventory i "
                    "JOIN products p ON p.id = i.product_id "
                    "WHERE p.sku = :sku"
                ),
                {"sku": str(sku)},
            ).fetchone()
            return int(row[0] or 0) if row else 0
    except Exception as exc:
        logger.debug("get_stock_level(%s) failed: %s", sku, exc)
        return 0


def batch_stock_levels(skus: List[str]) -> Dict[str, int]:
    """Return {sku: stock_count} for all SKUs in one query. Missing SKUs → 0.

    Uses LEFT JOIN so SKUs with no inventory row still appear in the result
    (stock=0 via COALESCE).  Joins through products because the inventory
    table has no sku column.
    """
    if not skus:
        return {}
    try:
        params = {f"s{i}": s for i, s in enumerate(skus)}
        placeholders = ", ".join(f":{k}" for k in params)
        with db_session() as db:
            rows = db.execute(
                _text(
                    f"SELECT p.sku, COALESCE(SUM(i.stock), 0) "
                    f"FROM products p "
                    f"LEFT JOIN inventory i ON i.product_id = p.id "
                    f"WHERE p.sku IN ({placeholders}) "
                    f"GROUP BY p.sku"
                ),
                params,
            ).fetchall()
        result = {str(r[0]): int(r[1] or 0) for r in rows}
        # Ensure every requested SKU is present (unknown SKUs → 0)
        for sku in skus:
            result.setdefault(sku, 0)
        return result
    except Exception as exc:
        logger.debug("batch_stock_levels failed: %s", exc)
        return {sku: 0 for sku in skus}


# ── Inventory rule evaluation (delegates to InventoryAgent) ──────────────────

def evaluate_stock_rule_for_sku(sku: str) -> Dict[str, Any]:
    """Return InventoryAgent rule evaluation for *sku*.

    Stock count is fetched from DB first; the LLM is never consulted.
    """
    stock = get_stock_level(sku)
    try:
        from src.app.services.inventory_agent import InventoryAgent
        agent = InventoryAgent()
        return agent.evaluate_stock_rule(sku, {"stock": stock})
    except Exception:
        if stock > 10:
            return {"rule_id": "R001", "action": "in_stock_message", "response": f"In stock ({stock} units)"}
        if stock > 0:
            return {"rule_id": "R002", "action": "limited_stock_message", "response": f"Only {stock} left"}
        return {"rule_id": "R004", "action": "unavailable_suggest_alt", "response": "Currently unavailable"}


# ── Public entry point for recommend.py ──────────────────────────────────────

def handle_inventory_intent(query: str, uid: str) -> Optional[Dict[str, Any]]:
    """If *query* is a stock query, return a direct DB-sourced response dict.

    Returns None if the query is not a stock intent so the caller falls through
    to the normal recommendation pipeline.

    Never calls an LLM. Stock counts are authoritative from the DB only.

    Example response:
        {
            "answer": "Only 3 left in stock — ships within 2 days",
            "sku": "LAPTOP-001",
            "stock_level": 3,
            "source": "inventory_agent_direct",
            "injection_blocked": False,
        }
    """
    # Injection guard — if injection detected, return safe refusal without DB lookup
    if has_injection_attempt(query):
        logger.warning("inventory_injection_attempt uid=%s query_snippet=%s", uid, (query or "")[:80])
        return {
            "answer": "I can look up stock levels for specific products. Which product are you interested in?",
            "source": "inventory_guard_blocked",
            "injection_blocked": True,
        }

    if not is_inventory_query(query):
        return None

    # Try to extract a specific product from the query
    candidates = fuzzy_sku_lookup(query, limit=1)
    if not candidates:
        # Could not identify a specific SKU — return a helpful nudge
        return {
            "answer": "I can check stock levels for you. Could you name the specific product or model?",
            "source": "inventory_no_sku_match",
            "injection_blocked": False,
        }

    product = candidates[0]
    sku = product["sku"]
    rule = evaluate_stock_rule_for_sku(sku)
    stock = get_stock_level(sku)

    return {
        "answer": rule.get("response", "Stock information unavailable"),
        "sku": sku,
        "name": product.get("name"),
        "brand": product.get("brand"),
        "stock_level": stock,
        "rule_id": rule.get("rule_id"),
        "source": "inventory_agent_direct",
        "injection_blocked": False,
    }
