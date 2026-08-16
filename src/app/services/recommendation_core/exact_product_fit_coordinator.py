"""Coordinate exact-product evidence and buyer-visible fit explanations.

This stage consumes an authorized slate and typed requirements.  It may resolve
additional exact-configuration evidence after buyer consent, but it never
selects a substitute, changes ranking, or gains commercial authority.
"""

from __future__ import annotations

from typing import Any


def coordinate_exact_product_fit(db: Any, envelope: Any, decision: Any, resp: Any) -> None:
    if "EXPLAIN" not in decision.secondary_lanes or not resp.products:
        return
    selected_sku = str(decision.exact_product_sku or "").strip()
    top = next((card for card in resp.products if card.sku == selected_sku), None)
    if selected_sku and top is None:
        resp.extras["explanation"] = {
            "sku": selected_sku,
            "status": "selected_product_not_in_authorized_slate",
            "verdict": None,
            "basis": [],
            "fit_ledger": [],
        }
        resp.message = (
            f"{resp.message.strip()} I cannot explain the selected product from this slate "
            "because its authorized catalog record was not returned; I will not substitute "
            "another product."
        ).strip()
        return
    top = top or resp.products[0]
    semantic = (
        resp.extras.get("semantic_resolution")
        if isinstance(resp.extras.get("semantic_resolution"), dict)
        else envelope.session.get("semantic_resolution")
        if isinstance(envelope.session.get("semantic_resolution"), dict)
        else {}
    )
    compilation = (
        resp.extras.get("semantic_requirement_compilation")
        if isinstance(resp.extras.get("semantic_requirement_compilation"), dict)
        else envelope.session.get("semantic_requirement_compilation")
        if isinstance(envelope.session.get("semantic_requirement_compilation"), dict)
        else {}
    )
    if semantic:
        resp.extras.setdefault("semantic_resolution", dict(semantic))
    if compilation:
        resp.extras.setdefault("semantic_requirement_compilation", dict(compilation))

    from src.app.services.recommendation_core.product_fit_explanation import (
        build_product_fit_explanation,
    )

    product_capability: dict[str, Any] = {
        "status": "not_requested",
        "commercial_authority_granted": False,
    }
    if envelope.external_research_consent and decision.exact_product_sku and decision.requirements:
        from src.app.services.catalog_read_model import get_variant
        from src.app.services.connectors.product_capability_evidence import (
            configured_product_capability_registry,
            identity_from_catalog_variant,
        )

        variant = get_variant(db, top.sku, tenant_id=envelope.tenant_id)
        if variant is not None:
            identity = identity_from_catalog_variant(variant)
            if identity.identifier:
                product_capability = configured_product_capability_registry().resolve(
                    identity,
                    claim_keys=tuple(decision.requirements),
                    allow_live=True,
                    tenant_id=envelope.tenant_id,
                ).to_dict()

    explanation_payload, explanation = build_product_fit_explanation(
        product=top,
        requirements=decision.requirements,
        semantic_resolution=semantic,
        requirement_compilation=compilation,
        product_capability_evidence=product_capability,
    )
    resp.extras["explanation"] = explanation_payload
    product_explanations: dict[str, dict[str, Any]] = {}
    for card in resp.products[:10]:
        card_payload, _ = build_product_fit_explanation(
            product=card,
            requirements=decision.requirements,
            semantic_resolution=semantic,
            requirement_compilation=compilation,
            product_capability_evidence=(
                product_capability if card.sku == top.sku else {
                    "status": "not_requested",
                    "commercial_authority_granted": False,
                }
            ),
        )
        product_explanations[str(card.sku)] = card_payload
    resp.extras["product_explanations"] = product_explanations
    current = str(resp.message or "").strip()
    if explanation not in current:
        resp.message = f"{current} {explanation}".strip()


__all__ = ["coordinate_exact_product_fit"]
