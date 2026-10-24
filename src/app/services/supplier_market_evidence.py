"""Read reviewed, current case quotations as bounded lead-time observations.

No new store, forecast, transport or ingestion framework is introduced. Supplier
quotation time is distinct from observed delivery performance and stock proof.
"""

from sqlalchemy import inspect, text


def current_case_lead_times(db, *, tenant_id, case_id, case_revision, skus, limit=5):
    if (
        not case_id
        or (not isinstance(case_revision, int) or isinstance(case_revision, bool))
        or not skus
        or db is None
    ):
        return []
    schema = inspect(db.connection())
    if not all(
        schema.has_table(table) for table in ("supplier_enquiry_request", "supplier_enquiry_reply")
    ):
        return []
    from src.app.services import supplier_enquiry_journey as journey
    from src.app.services.market_analysis import MarketFinding

    rows = (
        db.execute(
            text(
                "SELECT id FROM supplier_enquiry_request WHERE tenant_id=:tenant "
                "AND case_id=:case AND case_revision=:revision ORDER BY created_at DESC,id LIMIT :limit"
            ),
            dict(
                tenant=tenant_id, case=case_id, revision=case_revision, limit=max(1, min(limit, 10))
            ),
        )
        .scalars()
        .all()
    )
    findings = []
    for enquiry_id in rows:
        try:
            view = journey.view(db, tenant_id=tenant_id, enquiry_id=enquiry_id)
        except ValueError:
            continue  # Failed draft/current-case integrity cannot create an observation.
        if view["sku"] not in skus:
            continue
        for reply in view["quotes"]:
            if not reply["assessment"]["eligible"]:
                continue
            stored = db.execute(
                text(
                    "SELECT received_at FROM supplier_enquiry_reply "
                    "WHERE tenant_id=:tenant AND enquiry_id=:enquiry AND id=:id"
                ),
                dict(tenant=tenant_id, enquiry=enquiry_id, id=reply["id"]),
            ).scalar_one()
            terms = journey.QuoteTerms.model_validate(reply["terms"]).model_dump()
            quantity = reply["assessment"]["sourced_quantity"]
            prefix = (
                "Fictional supplier (simulation only)"
                if view.get("simulation_only")
                else "Supplier"
            )
            summary = (
                f"{prefix} quoted {terms['lead_days']} days for {quantity} units of {view['sku']}. "
                f"Quotation valid until {terms['expires_at']}; delivery is not confirmed."
            )
            evidence = dict(
                status="observed",
                subject_type="sku",
                subject_id=view["sku"],
                source_system="supplier_enquiry_review",
                source_record_id=reply["id"],
                lineage_root="supplier-enquiry:" + enquiry_id,
                provenance_chain=[enquiry_id, reply["id"]],
                observed_at=stored,
                effective_from=stored,
                effective_to=terms["expires_at"],
                authority="advisory",
                measurement_definition="Reviewed supplier-quoted lead time in calendar days",
                measurement_scope="This accepted case only; not delivery performance or physical stock",
                uom="days",
                magnitude_low=terms["lead_days"],
                magnitude_high=terms["lead_days"],
                coverage=dict(
                    case_id=case_id,
                    case_revision=case_revision,
                    quoted_quantity=quantity,
                    shortfall=view["shortfall"],
                    status=reply["assessment"]["coverage"],
                    simulation_only=bool(view.get("simulation_only")),
                ),
            )
            findings.append(
                MarketFinding(
                    "supplier_lead_time",
                    view["sku"],
                    "info",
                    1.0,
                    summary,
                    evidence,
                    "current-case-quotation",
                )
            )
    return findings
