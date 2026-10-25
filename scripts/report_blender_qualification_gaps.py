"""Read-only diagnosis from a captured official page and exact catalog evidence.

Does not enroll sources, accept claims, refresh facts or grant fit/commerce authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from src.app.models.orm import ProductConfiguration, ProductEvidenceObservation  # noqa: E402
from src.app.services.accepted_catalog_projection import _evidence_for_attribute, _verdict  # noqa: E402
from src.app.services.blender_requirement_parser import requirement_cells  # noqa: E402
from src.app.services.official_workload_research import compile_source_claims  # noqa: E402
from src.app.services.recommendation_core.requirement_compiler import compile_authoritative_requirements  # noqa: E402
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope  # noqa: E402


def report(*, content: bytes, database: Path, tenant: str, skus: list[str], observed_at: str):
    url = "https://www.blender.org/download/requirements/"
    claims, _ = compile_source_claims(
        "blender_official_requirements", content, observed_at=observed_at, citation_url=url,
    )
    selected = [r for r in claims if r["platform"] == "Windows"]
    scope = resolve_requirement_scope(tenant_id=tenant, profile_id="electronics",
                                     product_type="el-6-6", relationship="RUN_SUBJECT_ON_PRODUCT")
    engine = create_engine(f"sqlite:///file:{database.resolve().as_posix()}?mode=ro&uri=true")
    candidates = []
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        configurations = db.scalars(select(ProductConfiguration).where(
            ProductConfiguration.tenant_id == tenant, ProductConfiguration.sku.in_(skus),
        )).all()
        for config in configurations:
            observations = db.scalars(select(ProductEvidenceObservation).where(
                ProductEvidenceObservation.configuration_id == config.id,
            )).all()
            obligations = []
            for claim in selected:
                fact = _evidence_for_attribute(config, claim["attribute"], observations, now=now)
                # Diagnostic adapter only. Production enrolled claims do not enter
                # the authoritative compiler; demonstrate that no scope fails closed.
                proposal = dict(claim, status="accepted", authority="official_requirements",
                                attribute_key=claim["attribute"], claim_origin="observed",
                                source_record_id=claim["source_revision"],
                                lineage_root=claim["source_id"], confidence=1,
                                operator="=" if claim["operator"] == "equals" else claim["operator"])
                compilation = compile_authoritative_requirements([proposal], scope=None)
                blockers = [r["reason"] for r in compilation.rejections]
                if fact["contested"]:
                    blockers.append("product_fact_conflicted")
                elif fact["observed"] is None:
                    blockers.append("product_fact_missing")
                if fact["freshness"] != "fresh":
                    blockers.append("product_evidence_" + fact["freshness"])
                if not fact["verified"]:
                    blockers.append("product_fact_unverified")
                verdict = _verdict(claim, fact["observed"])
                if verdict != "meets_minimum":
                    blockers.append("literal_comparison_" + verdict)
                if claim["attribute"] == "operating_system" and verdict != "meets_minimum":
                    blockers.append("os_version_edition_compatibility_policy_missing")
                obligations.append(dict(source=claim, compiler_decision=list(compilation.rejections),
                                        product_fact=fact, literal_comparison=verdict, blockers=blockers))
            # Keep compound compatibility clauses visible. Numeric extraction is
            # not evidence that the rest of their source cell was compiled.
            for field, attribute, marker in (("CPU", "cpu_instruction_set", "SSE4.2"),
                                             ("GPU", "graphics_api", "OpenGL"),
                                             ("OS", "architecture_compatibility", "64-bit")):
                for cell in requirement_cells(content):
                    if cell["platform"] != "Windows" or cell["field"] != field or marker not in cell["text"]:
                        continue
                    fact = _evidence_for_attribute(config, attribute, observations, now=now)
                    obligations.append(dict(source={**cell, "citation_url": url}, attribute=attribute,
                                            extracted_value=None, compiler_decision="not_extracted",
                                            product_fact=fact, literal_comparison="unknown",
                                            blockers=["compatibility_clause_not_extracted_or_compiled"]))
            candidates.append(dict(sku=config.sku, mpn=config.mpn, configuration_id=config.id,
                                   configuration_hash=config.configuration_hash,
                                   source_url=config.source_url, obligations=obligations,
                                   qualified=False, commerce_authority="none"))
    engine.dispose()
    return dict(
        generated_at=now.isoformat(), source_url=url, observed_at=observed_at,
        source_sha256=hashlib.sha256(content).hexdigest(),
        diagnostic_only=True, tenant_id=tenant,
        scope={"application": "Blender", "version": None, "platform": "Windows",
               "tier": "recommended", "workload": "published application requirements; no performance promise"},
        extracted_claims=len(claims), source_cells=requirement_cells(content),
        candidate_configurations=candidates,
        requested_skus_not_found=sorted(set(skus) - {r["sku"] for r in candidates}),
        existing_manifest=scope.model_dump(mode="json") if scope else None,
        blockers=[
            "application_release_not_bound_by_moving_requirements_page",
            "enrolled_source_path_does_not_compile_into_pinned_manifest",
            "generic_manifest_requires_cpu_gpu_models_and_storage_not_published_in_this_table",
            "minimum_instruction_set_and_graphics_api_obligations_not_compiled",
            "minimum_and_recommended_platform_applicability_needs_explicit_contract",
        ],
        qualified=False, commerce_authority="none",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-html", type=Path, required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--sku", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = report(content=args.source_html.read_bytes(), database=args.database,
                    tenant=args.tenant, skus=args.sku, observed_at=args.observed_at)
    from src.app.services.requirement_contract import load_requirement_contract, assess_contract_coverage
    contract = load_requirement_contract(ROOT / "config/requirement_contracts/blender-5.0-windows-opengl.json")
    claims, _ = compile_source_claims("blender_official_requirements", args.source_html.read_bytes(),
                                    observed_at=args.observed_at,
                                    citation_url="https://www.blender.org/download/requirements/")
    result["bounded_contract"] = assess_contract_coverage(contract, context=contract.context, claims=claims)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "configurations": len(result["candidate_configurations"]),
                      "extracted_claims": result["extracted_claims"], "qualified": False}))


if __name__ == "__main__":
    main()
