from __future__ import annotations

from src.app.services.graph_retrieval import DurableFallbackGraphAdapter, GraphAdapter, InMemoryGraphAdapter


class _FailingPrimary(GraphAdapter):
    def upsert_relationship(
        self,
        *,
        source_type: str,
        source_id: str,
        relation: str,
        target_type: str,
        target_id: str,
        weight: float = 1.0,
    ):
        return {"ok": False, "backend": "primary", "reason": "synthetic_failure"}

    def related_entities(self, *, node_type: str, node_id: str, limit: int = 20):
        return []


def test_inmemory_graph_adapter_upsert_is_idempotent_per_edge():
    g = InMemoryGraphAdapter()
    g.upsert_relationship(
        source_type="account",
        source_id="a1",
        relation="USES_DEVICE",
        target_type="device",
        target_id="d1",
        weight=0.4,
    )
    g.upsert_relationship(
        source_type="account",
        source_id="a1",
        relation="USES_DEVICE",
        target_type="device",
        target_id="d1",
        weight=0.7,
    )
    rel = g.related_entities(node_type="account", node_id="a1", limit=10)
    assert len(rel) == 1
    assert rel[0]["node_id"] == "d1"
    assert float(rel[0]["weight"]) >= 0.7


def test_durable_fallback_graph_adapter_returns_memory_when_primary_fails(monkeypatch, tmp_path):
    log_path = tmp_path / "graph_fallback.jsonl"
    monkeypatch.setenv("GRAPH_RETRIEVAL_FALLBACK_PERSIST", "1")
    monkeypatch.setenv("GRAPH_RETRIEVAL_FALLBACK_LOG_PATH", str(log_path))

    g = DurableFallbackGraphAdapter(primary=_FailingPrimary(), fallback=InMemoryGraphAdapter())
    out = g.upsert_relationship(
        source_type="account",
        source_id="a1",
        relation="USES_IP",
        target_type="ip",
        target_id="10.0.0.9",
        weight=0.8,
    )
    assert out.get("fallback_written") is True

    rel = g.related_entities(node_type="account", node_id="a1", limit=10)
    assert rel
    assert any(str(x.get("node_type")) == "ip" for x in rel)
    assert log_path.exists()

