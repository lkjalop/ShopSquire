from src.app.security.email_enrichment import enrich_iocs


def test_ioc_enrichment_fusion_contains_provenance_and_weights(monkeypatch):
    monkeypatch.delenv("OTX_API_KEY", raising=False)
    out = enrich_iocs(
        [
            {"type": "domain", "value": "evil-payments.example", "denylisted": True, "allowlisted": False},
            {"type": "domain", "value": "trusted.example", "denylisted": False, "allowlisted": True},
        ]
    )
    assert isinstance(out.get("provider_weights"), dict)
    assert "local" in (out.get("provider_weights") or {})
    assert isinstance(out.get("items"), list) and out.get("items")
    first = out["items"][0]
    assert isinstance(first.get("provenance"), list)
    assert "contradiction_penalty" in first
