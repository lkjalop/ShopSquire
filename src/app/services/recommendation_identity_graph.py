from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Set

from sqlalchemy import text


_ALLOWED_KEYS = (
    "email",
    "email_hash",
    "device_fingerprint",
    "session_id",
    "customer_id",
    "phone_hash",
    "cookie_id",
    "ip_hash",
)


def _stable_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def ensure_identity_graph_tables(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommend_identity_edges (
                    id TEXT PRIMARY KEY,
                    uid_hash TEXT NOT NULL,
                    identity_type TEXT NOT NULL,
                    identity_hash TEXT NOT NULL,
                    confidence REAL DEFAULT 0.7,
                    source TEXT DEFAULT 'interaction',
                    metadata_json TEXT,
                    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_reco_identity_uid
                ON recommend_identity_edges(uid_hash)
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_reco_identity_key
                ON recommend_identity_edges(identity_type, identity_hash)
                """
            )
        )
    except Exception:
        pass


def register_identity_observations(
    db,
    *,
    uid_hash: str,
    context: Dict[str, Any] | None,
    source: str = "interaction",
) -> int:
    uid = str(uid_hash or "").strip()
    if not uid:
        return 0
    ctx = context if isinstance(context, dict) else {}
    ensure_identity_graph_tables(db)
    added = 0
    for key in _ALLOWED_KEYS:
        raw = str(ctx.get(key) or "").strip()
        if not raw:
            continue
        # If caller already provided a hash, keep it stable; otherwise hash now.
        ident = raw if key.endswith("_hash") else _stable_hash(raw)
        conf = 0.75 if key in ("device_fingerprint", "email_hash", "email", "customer_id") else 0.55
        params = {
            "id": str(uuid.uuid4()),
            "uid_hash": uid,
            "identity_type": key,
            "identity_hash": ident,
            "confidence": conf,
            "source": str(source or "interaction"),
            "metadata_json": json.dumps({"source": source}, ensure_ascii=False),
        }
        try:
            db.execute(
                text(
                    """
                    INSERT INTO recommend_identity_edges
                    (id, uid_hash, identity_type, identity_hash, confidence, source, metadata_json)
                    VALUES (:id, :uid_hash, :identity_type, :identity_hash, :confidence, :source, :metadata_json)
                    """
                ),
                params,
            )
            added += 1
        except Exception:
            try:
                db.execute(
                    text(
                        """
                        UPDATE recommend_identity_edges
                        SET confidence = :confidence,
                            source = :source,
                            metadata_json = :metadata_json,
                            last_seen = CURRENT_TIMESTAMP
                        WHERE uid_hash = :uid_hash
                          AND identity_type = :identity_type
                          AND identity_hash = :identity_hash
                        """
                    ),
                    params,
                )
            except Exception:
                pass
    return added


def linked_uid_hashes(db, uid_hash: str, max_depth: int = 2, max_nodes: int = 24) -> List[str]:
    uid = str(uid_hash or "").strip()
    if not uid:
        return []
    ensure_identity_graph_tables(db)
    seen: Set[str] = {uid}
    frontier: Set[str] = {uid}
    depth = 0
    while frontier and depth < max(1, int(max_depth)) and len(seen) < max_nodes:
        new_frontier: Set[str] = set()
        for node in list(frontier):
            try:
                keys = db.execute(
                    text(
                        """
                        SELECT identity_type, identity_hash
                        FROM recommend_identity_edges
                        WHERE uid_hash = :uid_hash
                        """
                    ),
                    {"uid_hash": node},
                ).fetchall()
            except Exception:
                keys = []
            for k in keys or []:
                i_type = str(k[0] or "")
                i_hash = str(k[1] or "")
                if not i_type or not i_hash:
                    continue
                try:
                    neighbors = db.execute(
                        text(
                            """
                            SELECT uid_hash
                            FROM recommend_identity_edges
                            WHERE identity_type = :identity_type
                              AND identity_hash = :identity_hash
                            ORDER BY confidence DESC, last_seen DESC
                            LIMIT 20
                            """
                        ),
                        {"identity_type": i_type, "identity_hash": i_hash},
                    ).fetchall()
                except Exception:
                    neighbors = []
                for n in neighbors or []:
                    nh = str(n[0] or "").strip()
                    if nh and nh not in seen:
                        seen.add(nh)
                        new_frontier.add(nh)
                        if len(seen) >= max_nodes:
                            break
                if len(seen) >= max_nodes:
                    break
            if len(seen) >= max_nodes:
                break
        frontier = new_frontier
        depth += 1
    return sorted(seen)


def apply_returning_customer_boost(
    db,
    *,
    uid_hash: str,
    product_scores: Dict[str, float],
    boost_config: Dict[str, Any] | None = None,
) -> Dict[str, float]:
    """Apply merchant-configurable boost weights for returning customers.

    Looks up the customer's identity graph to find past purchase patterns
    across linked sessions and boosts products matching their preferences.

    boost_config keys:
        brand_boost: float (default 0.05) — boost for preferred brands
        category_boost: float (default 0.03) — boost for frequently browsed categories
        returning_base_boost: float (default 0.02) — flat boost for being a returning customer
    """
    config = boost_config or {}
    brand_boost = float(config.get("brand_boost", 0.05))
    category_boost = float(config.get("category_boost", 0.03))
    returning_base = float(config.get("returning_base_boost", 0.02))

    linked = linked_uid_hashes(db, uid_hash, max_depth=1, max_nodes=10)
    if len(linked) <= 1:
        # Not a returning customer (only self in graph)
        return product_scores

    # Collect purchase signals from linked sessions
    past_skus: Set[str] = set()
    for linked_uid in linked:
        try:
            rows = db.execute(
                text("""
                    SELECT metadata_json FROM recommend_identity_edges
                    WHERE uid_hash = :uid AND source = 'purchase'
                    ORDER BY last_seen DESC LIMIT 20
                """),
                {"uid": linked_uid},
            ).fetchall()
            for r in rows:
                try:
                    meta = json.loads(r[0]) if r[0] else {}
                    for sku in meta.get("purchased_skus", []):
                        past_skus.add(str(sku))
                except Exception:
                    pass
        except Exception:
            pass

    # Apply boosts
    boosted = dict(product_scores)
    for sku, score in boosted.items():
        boost = returning_base  # flat returning customer boost
        if sku in past_skus:
            boost += brand_boost  # they bought this before — familiarity boost
        boosted[sku] = min(1.0, score + boost)

    return boosted
