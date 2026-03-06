from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
import os
import threading

from src.app.services import neo4j_graph


class GraphAdapter:
    def upsert_relationship(
        self,
        *,
        source_type: str,
        source_id: str,
        relation: str,
        target_type: str,
        target_id: str,
        weight: float = 1.0,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def related_entities(self, *, node_type: str, node_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        raise NotImplementedError


@dataclass
class InMemoryGraphAdapter(GraphAdapter):
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _adj: Dict[str, List[Tuple[str, str, float]]] = field(default_factory=dict)

    def _key(self, node_type: str, node_id: str) -> str:
        return f"{str(node_type).strip().lower()}:{str(node_id).strip()}"

    def upsert_relationship(
        self,
        *,
        source_type: str,
        source_id: str,
        relation: str,
        target_type: str,
        target_id: str,
        weight: float = 1.0,
    ) -> Dict[str, Any]:
        src = self._key(source_type, source_id)
        dst = self._key(target_type, target_id)
        rel = str(relation or "RELATED_TO").strip().upper()
        w = float(weight or 1.0)
        with self._lock:
            self._adj.setdefault(src, [])
            self._adj.setdefault(dst, [])
            self._adj[src].append((dst, rel, w))
            self._adj[dst].append((src, rel, w))
        return {"ok": True, "backend": "memory", "source": src, "target": dst, "relation": rel, "weight": w}

    def related_entities(self, *, node_type: str, node_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        key = self._key(node_type, node_id)
        with self._lock:
            rows = list(self._adj.get(key) or [])[: max(1, int(limit or 20))]
        out: List[Dict[str, Any]] = []
        for dst, rel, w in rows:
            t, _, nid = dst.partition(":")
            out.append({"node_type": t, "node_id": nid, "relation": rel, "weight": float(w)})
        return out


class Neo4jGraphAdapter(GraphAdapter):
    def upsert_relationship(
        self,
        *,
        source_type: str,
        source_id: str,
        relation: str,
        target_type: str,
        target_id: str,
        weight: float = 1.0,
    ) -> Dict[str, Any]:
        # Current production connector is focused on fraud/account nodes.
        if str(source_type).lower() == "account" and str(target_type).lower() in ("device", "ip", "address"):
            if str(target_type).lower() == "device":
                return neo4j_graph.upsert_account_device_ip_event(
                    account_id=source_id,
                    device_fingerprint=target_id,
                    source_ip=None,
                    shipping_address_hash=None,
                )
            if str(target_type).lower() == "ip":
                return neo4j_graph.upsert_account_device_ip_event(
                    account_id=source_id,
                    device_fingerprint=None,
                    source_ip=target_id,
                    shipping_address_hash=None,
                )
            if str(target_type).lower() == "address":
                return neo4j_graph.upsert_account_device_ip_event(
                    account_id=source_id,
                    device_fingerprint=None,
                    source_ip=None,
                    shipping_address_hash=target_id,
                )
        return {"ok": False, "backend": "neo4j", "reason": "relation_not_supported"}

    def related_entities(self, *, node_type: str, node_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        if str(node_type).lower() == "account":
            sig = neo4j_graph.account_device_ip_ring_signal(account_id=node_id, device_fingerprint=None, source_ip=None)
            return [
                {"node_type": "account", "node_id": node_id, "relation": "RING_SIGNAL", "weight": float(sig.get("ring_risk") or 0.0)}
            ]
        return []


_MEMORY_ADAPTER = InMemoryGraphAdapter()


def get_graph_adapter() -> GraphAdapter:
    backend = str(os.getenv("GRAPH_RETRIEVAL_BACKEND", "auto")).strip().lower()
    if backend == "memory":
        return _MEMORY_ADAPTER
    if backend == "neo4j":
        return Neo4jGraphAdapter()
    if bool(neo4j_graph._enabled()):
        return Neo4jGraphAdapter()
    return _MEMORY_ADAPTER

