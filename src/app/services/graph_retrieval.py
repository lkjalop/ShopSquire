from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
            # Upsert edge tuple instead of unbounded append to avoid duplicate drift.
            def _upsert(bucket_key: str, other: str) -> None:
                bucket = self._adj.get(bucket_key) or []
                replaced = False
                for i, (d, r, old_w) in enumerate(bucket):
                    if d == other and r == rel:
                        bucket[i] = (d, r, max(float(old_w), w))
                        replaced = True
                        break
                if not replaced:
                    bucket.append((other, rel, w))
                self._adj[bucket_key] = bucket

            _upsert(src, dst)
            _upsert(dst, src)
        return {"ok": True, "backend": "memory", "source": src, "target": dst, "relation": rel, "weight": w}

    def related_entities(self, *, node_type: str, node_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        key = self._key(node_type, node_id)
        with self._lock:
            rows = sorted(list(self._adj.get(key) or []), key=lambda x: float(x[2] or 0.0), reverse=True)[: max(1, int(limit or 20))]
        out: List[Dict[str, Any]] = []
        for dst, rel, w in rows:
            t, _, nid = dst.partition(":")
            out.append({"node_type": t, "node_id": nid, "relation": rel, "weight": float(w)})
        return out


class Neo4jGraphAdapter(GraphAdapter):
    @staticmethod
    def _norm_node_type(value: str) -> str:
        v = str(value or "").strip().lower()
        aliases = {
            "user": "account",
            "customer": "account",
            "acct": "account",
            "addr": "address",
        }
        return aliases.get(v, v)

    def _upsert_account_relation(
        self,
        *,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
    ) -> Dict[str, Any] | None:
        s = self._norm_node_type(source_type)
        t = self._norm_node_type(target_type)
        if s == "account" and t in ("device", "ip", "address"):
            if t == "device":
                return neo4j_graph.upsert_account_device_ip_event(
                    account_id=source_id,
                    device_fingerprint=target_id,
                    source_ip=None,
                    shipping_address_hash=None,
                )
            if t == "ip":
                return neo4j_graph.upsert_account_device_ip_event(
                    account_id=source_id,
                    device_fingerprint=None,
                    source_ip=target_id,
                    shipping_address_hash=None,
                )
            if t == "address":
                return neo4j_graph.upsert_account_device_ip_event(
                    account_id=source_id,
                    device_fingerprint=None,
                    source_ip=None,
                    shipping_address_hash=target_id,
                )
        if t == "account" and s in ("device", "ip", "address"):
            return self._upsert_account_relation(
                source_type=t,
                source_id=target_id,
                target_type=s,
                target_id=source_id,
            )
        return None

    def _generic_upsert(
        self,
        *,
        source_type: str,
        source_id: str,
        relation: str,
        target_type: str,
        target_id: str,
        weight: float,
    ) -> Dict[str, Any]:
        driver = neo4j_graph._get_driver()
        if driver is None:
            return {"ok": False, "backend": "neo4j", "reason": "neo4j_unavailable"}
        rel = str(relation or "RELATED_TO").strip().upper()
        q = """
        MERGE (s:Entity {type: $source_type, id: $source_id})
        MERGE (t:Entity {type: $target_type, id: $target_id})
        MERGE (s)-[r:RELATED_TO {kind: $relation}]->(t)
        SET r.weight = $weight, r.updated_at = datetime()
        """
        try:
            with driver.session() as sess:
                sess.run(
                    q,
                    source_type=self._norm_node_type(source_type),
                    source_id=str(source_id),
                    target_type=self._norm_node_type(target_type),
                    target_id=str(target_id),
                    relation=rel,
                    weight=float(weight or 1.0),
                ).consume()
            return {"ok": True, "backend": "neo4j", "relation": rel}
        except Exception:
            return {"ok": False, "backend": "neo4j", "reason": "neo4j_write_failed"}

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
        special = self._upsert_account_relation(
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
        )
        if special is not None:
            out = dict(special or {})
            out.setdefault("backend", "neo4j")
            return out
        return self._generic_upsert(
            source_type=source_type,
            source_id=source_id,
            relation=relation,
            target_type=target_type,
            target_id=target_id,
            weight=weight,
        )

    def related_entities(self, *, node_type: str, node_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        ntype = self._norm_node_type(node_type)
        if ntype == "account":
            sig = neo4j_graph.account_device_ip_ring_signal(account_id=node_id, device_fingerprint=None, source_ip=None)
            out.append(
                {
                    "node_type": "account",
                    "node_id": node_id,
                    "relation": "RING_SIGNAL",
                    "weight": float(sig.get("ring_risk") or 0.0),
                }
            )
        driver = neo4j_graph._get_driver()
        if driver is None:
            return out
        q = """
        MATCH (n:Entity {type: $node_type, id: $node_id})-[r:RELATED_TO]-(m:Entity)
        RETURN m.type AS node_type, m.id AS node_id, r.kind AS relation, r.weight AS weight
        ORDER BY coalesce(r.weight, 0.0) DESC
        LIMIT $limit
        """
        try:
            with driver.session() as sess:
                rows = sess.run(
                    q,
                    node_type=ntype,
                    node_id=str(node_id),
                    limit=max(1, int(limit or 20)),
                )
                for row in rows:
                    out.append(
                        {
                            "node_type": str(row.get("node_type") or ""),
                            "node_id": str(row.get("node_id") or ""),
                            "relation": str(row.get("relation") or "RELATED_TO"),
                            "weight": float(row.get("weight") or 0.0),
                        }
                    )
        except Exception:
            return out
        return out[: max(1, int(limit or 20))]


_MEMORY_ADAPTER = InMemoryGraphAdapter()
_DURABLE_IO_LOCK = threading.Lock()


def _fallback_log_path() -> Path:
    raw = str(os.getenv("GRAPH_RETRIEVAL_FALLBACK_LOG_PATH", "runs/graph_fallback_events.jsonl") or "").strip()
    return Path(raw or "runs/graph_fallback_events.jsonl")


def _append_fallback_event(payload: Dict[str, Any]) -> None:
    if str(os.getenv("GRAPH_RETRIEVAL_FALLBACK_PERSIST", "1")).strip().lower() not in ("1", "true", "yes", "on"):
        return
    path = _fallback_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False)
        with _DURABLE_IO_LOCK:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def _read_fallback_related(node_type: str, node_id: str, *, limit: int = 20) -> List[Dict[str, Any]]:
    path = _fallback_log_path()
    if not path.exists():
        return []
    key_a = f"{str(node_type).strip().lower()}:{str(node_id).strip()}"
    out: List[Dict[str, Any]] = []
    try:
        with _DURABLE_IO_LOCK:
            lines = path.read_text(encoding="utf-8").splitlines()[-4000:]
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            src = str(ev.get("source_key") or "")
            dst = str(ev.get("target_key") or "")
            rel = str(ev.get("relation") or "RELATED_TO")
            w = float(ev.get("weight") or 0.0)
            if src == key_a:
                t, _, nid = dst.partition(":")
                out.append({"node_type": t, "node_id": nid, "relation": rel, "weight": w})
            elif dst == key_a:
                t, _, nid = src.partition(":")
                out.append({"node_type": t, "node_id": nid, "relation": rel, "weight": w})
            if len(out) >= max(1, int(limit or 20)):
                break
    except Exception:
        return []
    return out


@dataclass
class DurableFallbackGraphAdapter(GraphAdapter):
    primary: GraphAdapter
    fallback: InMemoryGraphAdapter = field(default_factory=lambda: _MEMORY_ADAPTER)

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
        primary_out: Dict[str, Any] = {}
        try:
            primary_out = self.primary.upsert_relationship(
                source_type=source_type,
                source_id=source_id,
                relation=relation,
                target_type=target_type,
                target_id=target_id,
                weight=weight,
            )
        except Exception as exc:
            primary_out = {"ok": False, "backend": "primary", "reason": f"primary_exception:{str(exc)[:120]}"}
        fallback_out = self.fallback.upsert_relationship(
            source_type=source_type,
            source_id=source_id,
            relation=relation,
            target_type=target_type,
            target_id=target_id,
            weight=weight,
        )
        _append_fallback_event(
            {
                "ts": time.time(),
                "source_key": self._key(source_type, source_id),
                "target_key": self._key(target_type, target_id),
                "relation": str(relation or "RELATED_TO").strip().upper(),
                "weight": float(weight or 1.0),
                "primary_ok": bool(primary_out.get("ok")),
            }
        )
        out = dict(primary_out or {})
        out["fallback_written"] = bool(fallback_out.get("ok"))
        if not out.get("backend"):
            out["backend"] = "durable_fallback"
        return out

    def related_entities(self, *, node_type: str, node_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            rows = self.primary.related_entities(node_type=node_type, node_id=node_id, limit=limit)
            if rows:
                return rows[: max(1, int(limit or 20))]
        except Exception:
            pass
        rows = self.fallback.related_entities(node_type=node_type, node_id=node_id, limit=limit)
        if rows:
            return rows[: max(1, int(limit or 20))]
        return _read_fallback_related(node_type=node_type, node_id=node_id, limit=limit)


def get_graph_adapter() -> GraphAdapter:
    backend = str(os.getenv("GRAPH_RETRIEVAL_BACKEND", "auto")).strip().lower()
    if backend == "memory":
        return _MEMORY_ADAPTER
    if backend == "neo4j":
        if str(os.getenv("GRAPH_RETRIEVAL_DURABLE_FALLBACK", "1")).strip().lower() in ("1", "true", "yes", "on"):
            return DurableFallbackGraphAdapter(primary=Neo4jGraphAdapter(), fallback=_MEMORY_ADAPTER)
        return Neo4jGraphAdapter()
    if bool(neo4j_graph._enabled()):
        if str(os.getenv("GRAPH_RETRIEVAL_DURABLE_FALLBACK", "1")).strip().lower() in ("1", "true", "yes", "on"):
            return DurableFallbackGraphAdapter(primary=Neo4jGraphAdapter(), fallback=_MEMORY_ADAPTER)
        return Neo4jGraphAdapter()
    return _MEMORY_ADAPTER
