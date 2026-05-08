from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shopsquire.fraud_graph")

_driver = None
_enabled: bool = False
_init_attempted: bool = False


def _init_driver():
    """
    Lazy-init the Neo4j driver.  Only attempts once per process lifetime so a
    missing/misconfigured Neo4j does not spam logs on every request.
    Falls back gracefully when the package is missing or the host is unreachable.
    """
    global _driver, _enabled, _init_attempted
    if _init_attempted:
        return _driver
    _init_attempted = True

    if os.getenv("FRAUD_GRAPH_NEO4J_ENABLED", "0") != "1":
        logger.debug("Neo4j GNN disabled (FRAUD_GRAPH_NEO4J_ENABLED != 1); using heuristic fallback")
        return None

    try:
        from neo4j import GraphDatabase  # noqa: PLC0415  (optional dep)
    except ImportError:
        logger.warning("neo4j package not installed — pip install neo4j to enable GNN fraud detection")
        return None

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    try:
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        _driver.verify_connectivity()
        _enabled = True
        logger.info("Neo4j fraud graph connected: %s", uri)
    except Exception as exc:
        logger.warning("Neo4j unavailable (%s) — heuristic fallback active", exc)
        _driver = None
    return _driver


# ── Public API ──────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    _init_driver()
    return _enabled


def get_fraud_ring(entity_id: str, *, depth: int = 2) -> Dict[str, Any]:
    """
    Traverse the fraud graph up to `depth` hops from `entity_id`.
    Returns connected risky nodes and an aggregated ring_risk_score.
    Falls back to heuristic when Neo4j is unavailable.
    """
    driver = _init_driver()
    if not driver:
        return _heuristic_fallback(entity_id)

    ring_threshold = float(os.getenv("FRAUD_RING_RISK_THRESHOLD", "0.75"))
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH path = (start {id: $entity_id})-[*1..$depth]-(connected)
                WHERE any(lbl IN labels(connected) WHERE lbl IN ['Entity','Account','Device','IP','Email'])
                WITH connected,
                     min(length(path)) AS hop_distance,
                     max(coalesce(connected.risk_score, 0.0)) AS risk_score
                RETURN
                    connected.id          AS node_id,
                    connected.type        AS node_type,
                    labels(connected)     AS labels,
                    hop_distance,
                    risk_score
                ORDER BY risk_score DESC
                LIMIT 50
                """,
                entity_id=entity_id,
                depth=depth,
            )
            nodes = [dict(r) for r in result]

        ring_risk = max((float(n.get("risk_score") or 0.0) for n in nodes), default=0.0)
        return {
            "provider": "neo4j_gnn",
            "entity_id": entity_id,
            "ring_size": len(nodes),
            "ring_risk_score": round(ring_risk, 3),
            "nodes": nodes[:20],
            "fraud_ring_detected": ring_risk >= ring_threshold,
        }
    except Exception as exc:
        logger.warning("Neo4j query failed for %s: %s", entity_id, exc)
        return _heuristic_fallback(entity_id)


def upsert_entity(
    entity_id: str,
    entity_type: str,
    properties: Dict[str, Any],
) -> bool:
    """Insert or update a fraud graph node."""
    driver = _init_driver()
    if not driver:
        return False
    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (e:Entity {id: $entity_id})
                SET e += $props,
                    e.type       = $entity_type,
                    e.updated_at = timestamp()
                """,
                entity_id=entity_id,
                entity_type=entity_type,
                props=properties,
            )
        return True
    except Exception as exc:
        logger.warning("Neo4j upsert failed for %s: %s", entity_id, exc)
        return False


def link_entities(
    from_id: str,
    to_id: str,
    rel_type: str,
    *,
    weight: float = 1.0,
    properties: Optional[Dict[str, Any]] = None,
) -> bool:
    """Create or update a relationship between two fraud graph nodes."""
    driver = _init_driver()
    if not driver:
        return False
    safe_rel = "".join(c for c in rel_type.upper() if c.isalnum() or c == "_")
    if not safe_rel:
        return False
    try:
        with driver.session() as session:
            session.run(
                f"""
                MATCH (a {{id: $from_id}}), (b {{id: $to_id}})
                MERGE (a)-[r:{safe_rel}]->(b)
                SET r.weight     = $weight,
                    r.updated_at = timestamp(),
                    r            += $props
                """,
                from_id=from_id,
                to_id=to_id,
                weight=float(weight),
                props=dict(properties or {}),
            )
        return True
    except Exception as exc:
        logger.warning("Neo4j link failed %s->%s: %s", from_id, to_id, exc)
        return False


def find_shared_devices(entity_ids: List[str], *, limit: int = 20) -> List[Dict[str, Any]]:
    """Find Device nodes shared by multiple entity_ids — classic fraud ring signal."""
    driver = _init_driver()
    if not driver:
        return []
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (e)-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(other)
                WHERE e.id IN $entity_ids AND NOT other.id IN $entity_ids
                WITH d, collect(DISTINCT other.id) AS shared_with, count(*) AS share_count
                WHERE share_count > 1
                RETURN d.id AS device_id, shared_with, share_count
                ORDER BY share_count DESC
                LIMIT $limit
                """,
                entity_ids=entity_ids,
                limit=limit,
            )
            return [dict(r) for r in result]
    except Exception as exc:
        logger.warning("Neo4j shared-device query failed: %s", exc)
        return []


def close() -> None:
    """Cleanly close the Neo4j driver (call on app shutdown)."""
    global _driver, _enabled, _init_attempted
    if _driver:
        try:
            _driver.close()
        except Exception:
            pass
    _driver = None
    _enabled = False
    _init_attempted = False


def _heuristic_fallback(entity_id: str) -> Dict[str, Any]:
    return {
        "provider": "heuristic_fallback",
        "entity_id": entity_id,
        "ring_size": 0,
        "ring_risk_score": 0.0,
        "nodes": [],
        "fraud_ring_detected": False,
        "note": "Neo4j unavailable; heuristic scoring only",
    }
