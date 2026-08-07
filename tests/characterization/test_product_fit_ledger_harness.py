from __future__ import annotations

import pytest

from src.app.services.recommendation_core.envelope import ProductCard
from src.app.services.recommendation_core.product_fit_explanation import (
    build_product_fit_explanation,
)


@pytest.mark.parametrize(
    ("requirements", "per_key", "expected"),
    [
        ({"ram_gb": [[">=", 32]]}, {"ram_gb": True}, "meets"),
        ({"gpu_vram_gb": [[">=", 12]]}, {"gpu_vram_gb": False}, "fails"),
        ({"storage_gb": [[">=", 2048]]}, {"storage_gb": None}, "unknown"),
    ],
)
def test_same_product_different_workload_keeps_requirement_specific_ledger(
    requirements, per_key, expected,
):
    key = next(iter(requirements))
    observed = {"ram_gb": 64, "gpu_vram_gb": 8}
    product = ProductCard(
        sku="WORKSTATION-1", title="Portable workstation",
        fit={"overall": expected, "per_key": per_key, "observed": observed},
    )
    payload, _ = build_product_fit_explanation(
        product=product,
        requirements=requirements,
        semantic_resolution={"desired_outcome": f"workload requiring {key}"},
    )
    assert [row["attribute"] for row in payload["fit_ledger"]] == [key]
    assert payload["fit_ledger"][0]["verdict"] == expected


def test_changed_sku_cannot_reuse_prior_product_evidence():
    product = ProductCard(
        sku="WORKSTATION-2", title="Different workstation",
        fit={"overall": "unknown", "per_key": {"ram_gb": None}, "observed": {}},
    )
    payload, _ = build_product_fit_explanation(
        product=product,
        requirements={"ram_gb": [[">=", 32]]},
        product_capability_evidence={
            "status": "rejected",
            "identity": {"sku": "WORKSTATION-1"},
            "accepted_claims": [],
            "attempts": [{"status": "rejected", "reason": "product_identity_mismatch"}],
        },
    )
    assert payload["sku"] == "WORKSTATION-2"
    assert payload["fit_ledger"][0]["product_evidence_refs"] == []
    assert payload["product_capability_evidence"]["status"] == "rejected"
