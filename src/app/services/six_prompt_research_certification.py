"""Deterministic six-prompt research certification fixture.

This is deliberately a *fixture*, not a live-network implementation.  It proves
that one data-driven planner, claim compiler, and product reducer can process
materially different workloads without teaching the reducer vertical names.
Search results discover allowlisted origins; only claims attached to an official
origin are compiled into requirements.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


Operator = Literal["at_least", "equals"]
Fit = Literal["qualified", "conditional", "failed"]


class OriginClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    source_url: str
    attribute: str
    operator: Operator
    value: Any
    scope: str
    claim_class: Literal["attested", "derived", "behavioural"] = "attested"


class ScenarioFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    prompt: str
    hypotheses: list[str]
    material_question: str
    spanning_queries: dict[str, str]
    origin_claims: list[OriginClaim]
    unresolved: list[str] = Field(default_factory=list)
    architecture_alternatives: list[str] = Field(default_factory=list)


class CatalogFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    title: str
    price_cents: int
    attributes: dict[str, Any]


class ExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: Literal["searxng_fixture", "official_origin_fixture"]
    capability: Literal["WEB_DISCOVERY", "OFFICIAL_ORIGIN_FETCH"]
    request_hash: str
    fixture: Literal[True] = True
    network_execution: Literal[False] = False
    billing_class: Literal["free"] = "free"
    cache_status: Literal["miss"] = "miss"
    result_count: int = Field(ge=0)


class FitResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    title: str
    price_cents: int
    status: Fit
    meets: list[str]
    unknowns: list[str]
    misses: list[str]
    behavioural_performance: Literal["not_verified"] = "not_verified"


class CertificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    hypotheses: list[str]
    material_question: str
    queries: dict[str, str]
    searxng_responses: list[dict[str, Any]]
    accepted_claims: list[OriginClaim]
    requirement_graph_hash: str
    unresolved: list[str]
    products: list[FitResult]
    architecture_alternatives: list[str]
    receipts: list[ExecutionReceipt]
    fixture_dispatches: int
    external_calls: Literal[0] = 0
    paid_calls: Literal[0] = 0
    execution_mode: Literal["deterministic_fixture"] = "deterministic_fixture"


ALLOWED_OFFICIAL_DOMAINS = frozenset({
    "www.nist.gov",
    "csrc.nist.gov",
    "nvlpubs.nist.gov",
    "attack.mitre.org",
    "learn.microsoft.com",
    "docs.factoryio.com",
    "www.blender.org",
    "help.autodesk.com",
    "dev.epicgames.com",
})


def _claim(
    claim_id: str,
    url: str,
    attribute: str,
    value: Any,
    scope: str,
    *,
    operator: Operator = "at_least",
) -> OriginClaim:
    return OriginClaim(
        claim_id=claim_id,
        source_url=url,
        attribute=attribute,
        operator=operator,
        value=value,
        scope=scope,
    )


NIST_TWIN = "https://www.nist.gov/digital-twins"
BLENDER_REQ = "https://www.blender.org/download/requirements/"
AUTOCAD_REQ = "https://help.autodesk.com/view/ACD/2026/ENU/system-requirements"
REVIT_REQ = "https://help.autodesk.com/view/RVT/2026/ENU/system-requirements"
UNREAL_REQ = "https://dev.epicgames.com/documentation/en-us/unreal-engine/hardware-and-software-specifications-for-unreal-engine"
FACTORY_IO = "https://docs.factoryio.com/manual/system-requirements/"
HYPERV = "https://learn.microsoft.com/windows-server/virtualization/hyper-v/system-requirements-for-hyper-v-on-windows"
MITRE_ICS = "https://attack.mitre.org/matrices/ics/"


SCENARIOS: tuple[ScenarioFixture, ...] = (
    ScenarioFixture(
        scenario_id="predictive_digital_twin",
        prompt="I need a laptop for digital-twin simulation of factory equipment and predicting breakdowns.",
        hypotheses=["predictive-maintenance analytics", "process simulation", "local visual/physics twin"],
        material_question="Which named simulation or analytics software will run locally, and at what model scale?",
        spanning_queries={
            "concept": "official manufacturing digital twin predictive maintenance",
            "requirements": "official digital twin simulation system requirements named software",
        },
        origin_claims=[_claim("nist-twin-scope", NIST_TWIN, "digital_twin_scope", "predictive_maintenance", "concept", operator="equals")],
        unresolved=["CPU, RAM and GPU floor require a named local application and scale"],
        architecture_alternatives=["laptop", "fixed workstation", "cloud analytics"],
    ),
    ScenarioFixture(
        scenario_id="cgi_rendering",
        prompt="I do CGI; I don't want renders taking all night.",
        hypotheses=["GPU rendering", "CPU rendering", "real-time rendering"],
        material_question="Which renderer do you use, and will final renders run locally or on a render farm?",
        spanning_queries={
            "concept": "official CGI rendering hardware requirements",
            "requirements": "official Blender hardware requirements GPU rendering",
        },
        origin_claims=[
            _claim("blender-ram", BLENDER_REQ, "ram_gb", 32, "Blender recommended"),
            _claim("blender-vram", BLENDER_REQ, "gpu_vram_gb", 8, "Blender recommended"),
        ],
        unresolved=["render duration is not verified for an exact scene and configuration"],
        architecture_alternatives=["laptop", "fixed workstation", "render farm"],
    ),
    ScenarioFixture(
        scenario_id="large_cad_point_cloud",
        prompt="I need CAD for very large 3D models and point-cloud work.",
        hypotheses=["large-dataset CAD and point-cloud workstation"],
        material_question="Which CAD application and release must be supported?",
        spanning_queries={
            "requirements": "official AutoCAD large datasets point clouds system requirements",
            "certification": "official AutoCAD workstation graphics requirement",
        },
        origin_claims=[
            _claim("acad-ram", AUTOCAD_REQ, "ram_gb", 32, "large datasets and point clouds"),
            _claim("acad-vram", AUTOCAD_REQ, "gpu_vram_gb", 12, "large datasets and point clouds"),
            _claim("acad-gpu", AUTOCAD_REQ, "gpu_class", "professional", "large datasets and point clouds", operator="equals"),
        ],
        architecture_alternatives=["mobile workstation", "fixed workstation"],
    ),
    ScenarioFixture(
        scenario_id="ot_plc_cyber_range",
        prompt="I need to simulate a PLC-controlled factory and cyberattacks against the OT network.",
        hypotheses=["VM/network-appliance cyber range", "Factory I/O and PLC simulation"],
        material_question="How many simultaneous VMs, PLC/SCADA nodes, and monitoring systems will run?",
        spanning_queries={
            "concept": "official OT cyber range PLC factory simulation",
            "compatibility": "official Factory IO supported PLC drivers",
            "virtualisation": "official Hyper-V host requirements",
            "threat_topology": "official MITRE ATT&CK ICS matrix",
        },
        origin_claims=[
            _claim("hyperv-virt", HYPERV, "hardware_virtualisation", True, "Hyper-V host", operator="equals"),
            _claim("factoryio-plc", FACTORY_IO, "factory_io_compatible", True, "Factory I/O", operator="equals"),
            _claim("mitre-topology", MITRE_ICS, "ot_network_scenarios", True, "threat topology only", operator="equals"),
        ],
        unresolved=["RAM and CPU capacity depend on simultaneous node count"],
        architecture_alternatives=["laptop", "fixed workstation", "server-hosted cyber range"],
    ),
    ScenarioFixture(
        scenario_id="bim_walkthrough",
        prompt="I'm an architect working with large BIM models and real-time walkthroughs.",
        hypotheses=["large Revit BIM", "real-time walkthrough rendering"],
        material_question="What model size and walkthrough renderer do you use?",
        spanning_queries={
            "requirements": "official Revit large complex model system requirements",
            "walkthrough": "official real-time walkthrough renderer requirements",
        },
        origin_claims=[
            _claim("revit-ram", REVIT_REQ, "ram_gb", 64, "large complex model"),
            _claim("revit-vram", REVIT_REQ, "gpu_vram_gb", 8, "large complex model"),
        ],
        unresolved=["walkthrough renderer remains unnamed"],
        architecture_alternatives=["mobile workstation", "fixed workstation", "hosted rendering"],
    ),
    ScenarioFixture(
        scenario_id="unreal_nanite_lumen",
        prompt="I build Unreal Engine games with Nanite and Lumen.",
        hypotheses=["Unreal Engine development with Nanite and Lumen"],
        material_question="How large is the project and will shader and code compilation run locally?",
        spanning_queries={
            "requirements": "official Unreal Engine Nanite Lumen hardware requirements",
            "features": "official Unreal Engine Nanite Lumen DirectX 12 requirements",
        },
        origin_claims=[
            _claim("ue-ram", UNREAL_REQ, "ram_gb", 32, "Unreal development"),
            _claim("ue-vram", UNREAL_REQ, "gpu_vram_gb", 8, "Unreal development"),
            _claim("ue-dx12", UNREAL_REQ, "directx_12", True, "Nanite and Lumen", operator="equals"),
        ],
        unresolved=["compile time and frame rate are not verified for the exact project"],
        architecture_alternatives=["laptop", "fixed workstation", "distributed build worker"],
    ),
)


CATALOG: tuple[CatalogFixture, ...] = (
    CatalogFixture(
        sku="WS-MOBILE-01", title="Reviewed RTX Pro Mobile Workstation", price_cents=749_900,
        attributes={"ram_gb": 64, "gpu_vram_gb": 16, "gpu_class": "professional", "hardware_virtualisation": True, "factory_io_compatible": True, "ot_network_scenarios": True, "directx_12": True},
    ),
    CatalogFixture(
        sku="SCORP-126982", title="MSI Titan 18 HX Gaming Laptop", price_cents=899_900,
        attributes={"ram_gb": 64, "gpu_vram_gb": 24, "gpu_class": "consumer", "hardware_virtualisation": True, "factory_io_compatible": True, "ot_network_scenarios": True, "directx_12": True},
    ),
    CatalogFixture(
        sku="MID-GAME-01", title="RTX Gaming Laptop", price_cents=399_900,
        attributes={"ram_gb": 32, "gpu_vram_gb": 8, "gpu_class": "consumer", "hardware_virtualisation": True, "factory_io_compatible": True, "ot_network_scenarios": True, "directx_12": True},
    ),
    CatalogFixture(
        sku="VALUE-01", title="Value Laptop", price_cents=199_900,
        attributes={"ram_gb": 16, "gpu_vram_gb": 6, "gpu_class": "consumer", "hardware_virtualisation": True, "directx_12": True},
    ),
)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _fit(product: CatalogFixture, claims: list[OriginClaim], unresolved: list[str]) -> FitResult:
    meets: list[str] = []
    misses: list[str] = []
    unknowns = list(unresolved)
    for claim in claims:
        observed = product.attributes.get(claim.attribute)
        if observed is None:
            unknowns.append(claim.attribute)
            continue
        passed = observed >= claim.value if claim.operator == "at_least" else observed == claim.value
        (meets if passed else misses).append(claim.attribute)
    status: Fit = "failed" if misses else "conditional" if unknowns or not claims else "qualified"
    return FitResult(
        sku=product.sku,
        title=product.title,
        price_cents=product.price_cents,
        status=status,
        meets=meets,
        unknowns=list(dict.fromkeys(unknowns)),
        misses=misses,
    )


def certify_six_prompt_fixture(prompt: str) -> CertificationResult:
    """Execute the data-driven fixture planner/compiler/reducer for one prompt."""
    scenario = next((item for item in SCENARIOS if item.prompt.casefold() == prompt.strip().casefold()), None)
    if scenario is None:
        raise ValueError("prompt_not_in_certification_fixture")

    search_responses: list[dict[str, Any]] = []
    receipts: list[ExecutionReceipt] = []
    origins = list(dict.fromkeys(claim.source_url for claim in scenario.origin_claims))
    for purpose, query in scenario.spanning_queries.items():
        results = [
            {"title": f"Official evidence for {purpose}", "url": url, "content": "Discovery snippet is not accepted evidence."}
            for url in origins
        ]
        search_responses.append({"query": query, "number_of_results": len(results), "results": results})
        receipts.append(ExecutionReceipt(
            provider_id="searxng_fixture", capability="WEB_DISCOVERY",
            request_hash=_hash({"purpose": purpose, "query": query}), result_count=len(results),
        ))

    accepted = [
        claim for claim in scenario.origin_claims
        if (urlparse(claim.source_url).hostname or "").lower() in ALLOWED_OFFICIAL_DOMAINS
    ]
    for url in origins:
        origin_claim_count = sum(claim.source_url == url for claim in accepted)
        receipts.append(ExecutionReceipt(
            provider_id="official_origin_fixture", capability="OFFICIAL_ORIGIN_FETCH",
            request_hash=_hash(url), result_count=origin_claim_count,
        ))

    products = [_fit(product, accepted, scenario.unresolved) for product in CATALOG]
    products.sort(key=lambda item: (
        0 if item.status == "qualified" else 1 if item.status == "conditional" else 2,
        len(item.misses), len(item.unknowns), item.price_cents, item.sku,
    ))
    graph_material = [
        (claim.attribute, claim.operator, claim.value, claim.scope)
        for claim in accepted
    ] + [("unresolved", value) for value in scenario.unresolved]
    return CertificationResult(
        scenario_id=scenario.scenario_id,
        hypotheses=scenario.hypotheses,
        material_question=scenario.material_question,
        queries=scenario.spanning_queries,
        searxng_responses=search_responses,
        accepted_claims=accepted,
        requirement_graph_hash=_hash(graph_material),
        unresolved=scenario.unresolved,
        products=products,
        architecture_alternatives=scenario.architecture_alternatives,
        receipts=receipts,
        fixture_dispatches=len(receipts),
    )


__all__ = [
    "ALLOWED_OFFICIAL_DOMAINS",
    "CATALOG",
    "SCENARIOS",
    "CertificationResult",
    "certify_six_prompt_fixture",
]
