from src.app.services.recommendation_core.envelope import ProductCard
from src.app.services.recommendation_core.product_fit_explanation import (
    build_product_fit_explanation,
)


def test_product_evidence_confirms_catalog_without_overriding_fit():
    product = ProductCard(
        sku="SKU-A",
        title="Mobile workstation",
        fit={
            "overall": "meets",
            "per_key": {"ram_gb": True, "gpu_vram_gb": True},
            "observed": {"ram_gb": 32, "gpu_vram_gb": 8},
        },
    )
    payload, narration = build_product_fit_explanation(
        product=product,
        requirements={"ram_gb": [[">=", 32]], "gpu_vram_gb": [[">=", 8]]},
        product_capability_evidence={
            "status": "accepted",
            "accepted_claims": [{
                "attribute_key": "ram_gb", "value": 32,
                "source_record_id": "official-model-record",
            }],
        },
    )
    assert payload["fit_ledger"][0]["product_evidence_verdict"] == "confirms_catalog"
    assert payload["fit_ledger"][1]["product_evidence_verdict"] is None
    assert "confirms 1 compared configuration fact" in narration


def test_product_evidence_conflict_is_visible_and_does_not_rewrite_observation():
    product = ProductCard(
        sku="SKU-A", title="Mobile workstation",
        fit={"overall": "meets", "per_key": {"ram_gb": True}, "observed": {"ram_gb": 32}},
    )
    payload, _ = build_product_fit_explanation(
        product=product,
        requirements={"ram_gb": [[">=", 32]]},
        product_capability_evidence={
            "status": "accepted",
            "accepted_claims": [{"attribute_key": "ram_gb", "value": 64}],
        },
    )
    row = payload["fit_ledger"][0]
    assert row["observed"] == 32
    assert row["product_evidence_verdict"] == "conflicts_with_catalog"
