"""Typed, provider-neutral product capability evidence.

Providers identify a concrete catalog product and return bounded specification
claims. This registry validates product identity, publisher/domain policy,
freshness, and conflicts. It never selects products and never fills missing
configuration facts from a product family or marketing title.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProductIdentity:
    sku: str
    identifier_type: str
    identifier: str
    configuration_hash: str = ""
    form_factor: str = "unknown"


@dataclass(frozen=True)
class ProductSourcePolicy:
    provider_id: str
    allowed_publishers: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    max_age_seconds: int = 30 * 24 * 60 * 60
    allowed_identity_types: tuple[str, ...] = (
        "machine_type_model", "manufacturer_part_number", "gtin", "family_identifier",
    )


@dataclass(frozen=True)
class ProductCapabilityEvidence:
    provider_id: str
    source_type: str
    publisher: str
    source_url: str
    source_record_id: str
    retrieved_at: str
    identity: ProductIdentity
    claims: tuple[Mapping[str, Any], ...] = ()
    provenance_chain: tuple[str, ...] = ()
    parser_id: str = ""
    http_status: int | None = None
    response_body_sha256: str = ""


class ProductCapabilityEvidenceProvider(Protocol):
    provider_id: str
    source_types: tuple[str, ...]

    def resolve(
        self,
        identity: ProductIdentity,
        *,
        claim_keys: tuple[str, ...],
        allow_live: bool,
    ) -> Optional[ProductCapabilityEvidence]:
        ...


@dataclass(frozen=True)
class ProductCapabilityResolution:
    status: str
    identity: ProductIdentity
    accepted_claims: tuple[dict[str, Any], ...] = ()
    unknown_claim_keys: tuple[str, ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    attempts: tuple[dict[str, Any], ...] = ()
    tool_selection_receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "identity": {
                "sku": self.identity.sku,
                "identifier_type": self.identity.identifier_type,
                "identifier": self.identity.identifier,
                "configuration_hash": self.identity.configuration_hash,
                "form_factor": self.identity.form_factor,
            },
            "accepted_claims": list(self.accepted_claims),
            "unknown_claim_keys": list(self.unknown_claim_keys),
            "conflicts": list(self.conflicts),
            "attempts": list(self.attempts),
            "tool_selection_receipt": self.tool_selection_receipt,
            "commercial_authority_granted": False,
        }


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _domain_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    return bool(host) and any(
        host == item.lower().rstrip(".") or host.endswith("." + item.lower().rstrip("."))
        for item in allowed
    )


def _age_seconds(value: str) -> Optional[float]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _identity_matches(expected: ProductIdentity, actual: ProductIdentity) -> bool:
    if _normalized(expected.sku) != _normalized(actual.sku):
        return False
    if _normalized(expected.identifier_type) != _normalized(actual.identifier_type):
        return False
    if _normalized(expected.identifier) != _normalized(actual.identifier):
        return False
    if expected.configuration_hash and actual.configuration_hash:
        if _normalized(expected.configuration_hash) != _normalized(actual.configuration_hash):
            return False
    if expected.form_factor != "unknown" and actual.form_factor != "unknown":
        if _normalized(expected.form_factor) != _normalized(actual.form_factor):
            return False
    return True


class ProductCapabilityEvidenceRegistry:
    def __init__(
        self,
        *,
        providers: Iterable[ProductCapabilityEvidenceProvider] = (),
        policies: Iterable[ProductSourcePolicy] = (),
        allowed_tenants: Iterable[str] = ("*",),
    ) -> None:
        self._providers = list(providers)
        self._policies = {item.provider_id: item for item in policies}
        self._allowed_tenants = frozenset(str(item).strip() for item in allowed_tenants if str(item).strip())

    def resolve(
        self,
        identity: ProductIdentity,
        *,
        claim_keys: tuple[str, ...],
        allow_live: bool,
        tenant_id: str = "default",
    ) -> ProductCapabilityResolution:
        requested = tuple(dict.fromkeys(str(key).strip() for key in claim_keys if str(key).strip()))
        from src.app.services.tool_capability_selector import (
            ToolCapability, ToolDeployment, ToolHealth, ToolPolicy, ToolRequirement,
            select_tool_deployments,
        )
        allowed_tenants = tuple(self._allowed_tenants)
        deployments = tuple(
            ToolDeployment(
                deployment_id=provider.provider_id,
                capabilities=(ToolCapability.OEM_PRODUCT_SPECIFICATION,),
                policy=ToolPolicy(
                    allowed_tenants=allowed_tenants,
                    authority_score=95,
                    freshness_state="unknown",
                    side_effect_class="external_read",
                    cost_units=0,
                ),
                health=ToolHealth(status="unknown"),
            )
            for provider in self._providers
            if provider.provider_id in self._policies
        )
        selection = select_tool_deployments(
            ToolRequirement(
                capability=ToolCapability.OEM_PRODUCT_SPECIFICATION,
                tenant_id=str(tenant_id or "default"),
                max_cost_units=0,
                permitted_side_effects=("none", "external_read") if allow_live else ("none",),
            ),
            deployments,
            max_results=max(1, len(deployments)),
        )
        selection_dict = selection.model_dump(mode="json")
        if "*" not in self._allowed_tenants and str(tenant_id or "").strip() not in self._allowed_tenants:
            return ProductCapabilityResolution(
                status="blocked",
                identity=identity,
                unknown_claim_keys=requested,
                attempts=({"provider_id": None, "status": "tenant_not_allowed"},),
                tool_selection_receipt=selection_dict,
            )
        attempts: list[dict[str, Any]] = []
        gathered: list[dict[str, Any]] = []
        selected_ids = set(selection.selected_deployment_ids)
        for provider in self._providers:
            if provider.provider_id not in selected_ids:
                attempts.append({
                    "provider_id": provider.provider_id,
                    "status": "not_selected_by_tool_scope",
                })
                continue
            policy = self._policies.get(provider.provider_id)
            if policy is None:
                attempts.append({"provider_id": provider.provider_id, "status": "rejected", "reason": "source_policy_missing"})
                continue
            try:
                evidence = provider.resolve(identity, claim_keys=requested, allow_live=allow_live)
            except Exception as exc:
                attempts.append({
                    "provider_id": provider.provider_id,
                    "status": "provider_error",
                    "error_type": type(exc).__name__,
                })
                continue
            if evidence is None:
                attempts.append({"provider_id": provider.provider_id, "status": "no_result"})
                continue
            reason = self._rejection_reason(identity, evidence, policy)
            if reason:
                attempts.append({"provider_id": provider.provider_id, "status": "rejected", "reason": reason})
                continue
            accepted_count = 0
            for raw in evidence.claims[:64]:
                key = str(raw.get("attribute_key") or "").strip()
                if key not in requested or raw.get("value") is None:
                    continue
                claim = {
                    "attribute_key": key,
                    "value": raw.get("value"),
                    "unit": raw.get("unit"),
                    "confidence": float(raw.get("confidence") or 0.0),
                    "provider_id": evidence.provider_id,
                    "source_type": evidence.source_type,
                    "publisher": evidence.publisher,
                    "source_url": evidence.source_url,
                    "source_record_id": evidence.source_record_id,
                    "retrieved_at": evidence.retrieved_at,
                    "identity_type": evidence.identity.identifier_type,
                    "identity_value": evidence.identity.identifier,
                    "configuration_hash": evidence.identity.configuration_hash,
                    "form_factor": evidence.identity.form_factor,
                    "claim_class": (
                        str(raw.get("claim_class") or "attested").strip().lower()
                        if str(raw.get("claim_class") or "attested").strip().lower()
                        in {"attested", "derived", "behavioral"}
                        else "attested"
                    ),
                    "scope_caveat": str(raw.get("scope_caveat") or "").strip()[:500] or None,
                    "freshness_status": "fresh",
                    "provenance_chain": list(evidence.provenance_chain),
                }
                gathered.append(claim)
                accepted_count += 1
            attempts.append({
                "provider_id": provider.provider_id,
                "status": "accepted",
                "claim_count": accepted_count,
            })

        by_key: dict[str, list[dict[str, Any]]] = {}
        for claim in gathered:
            by_key.setdefault(claim["attribute_key"], []).append(claim)
        conflicts: list[dict[str, Any]] = []
        accepted: list[dict[str, Any]] = []
        for key, claims in by_key.items():
            values = {(_normalized(item.get("value")), _normalized(item.get("unit"))) for item in claims}
            if len(values) > 1:
                conflicts.append({
                    "attribute_key": key,
                    "values": [
                        {"value": item.get("value"), "unit": item.get("unit"), "provider_id": item["provider_id"]}
                        for item in claims
                    ],
                })
                continue
            accepted.append(max(claims, key=lambda item: item["confidence"]))
        conflict_keys = {item["attribute_key"] for item in conflicts}
        unknown = tuple(key for key in requested if key not in by_key or key in conflict_keys)
        if conflicts:
            status = "conflict"
        elif accepted:
            status = "accepted"
        elif any(item.get("status") == "rejected" for item in attempts):
            status = "rejected"
        else:
            status = "unavailable"
        return ProductCapabilityResolution(
            status=status,
            identity=identity,
            accepted_claims=tuple(accepted),
            unknown_claim_keys=unknown,
            conflicts=tuple(conflicts),
            attempts=tuple(attempts),
            tool_selection_receipt=selection_dict,
        )

    @staticmethod
    def _rejection_reason(
        expected: ProductIdentity,
        evidence: ProductCapabilityEvidence,
        policy: ProductSourcePolicy,
    ) -> Optional[str]:
        if evidence.provider_id != policy.provider_id:
            return "provider_identity_mismatch"
        if evidence.identity.identifier_type not in policy.allowed_identity_types:
            return "identity_type_not_allowed"
        if not _identity_matches(expected, evidence.identity):
            return "product_identity_mismatch"
        if _normalized(evidence.publisher) not in {_normalized(item) for item in policy.allowed_publishers}:
            return "publisher_not_allowed"
        if not _domain_allowed(evidence.source_url, policy.allowed_domains):
            return "source_domain_not_allowed"
        age = _age_seconds(evidence.retrieved_at)
        if age is None:
            return "retrieved_at_invalid"
        if age > max(0, int(policy.max_age_seconds)):
            return "evidence_stale"
        if not str(evidence.source_record_id or "").strip():
            return "source_record_id_missing"
        return None


def load_product_source_policies(path: Path | None = None) -> tuple[ProductSourcePolicy, ...]:
    """Load official-source enrollment as data; malformed entries are not enrolled."""
    source_path = path or (
        Path(__file__).resolve().parents[4] / "config" / "product_capability_sources.json"
    )
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return ()
    policies: list[ProductSourcePolicy] = []
    for raw in list(payload.get("sources") or [])[:32]:
        if not isinstance(raw, Mapping) or not bool(raw.get("enabled", True)):
            continue
        provider_id = str(raw.get("provider_id") or "").strip()
        publishers = tuple(str(item).strip() for item in raw.get("allowed_publishers") or () if str(item).strip())
        domains = tuple(str(item).strip().lower() for item in raw.get("allowed_domains") or () if str(item).strip())
        if not provider_id or not publishers or not domains:
            continue
        try:
            max_age = int(raw.get("max_age_seconds") or 30 * 24 * 60 * 60)
        except (TypeError, ValueError):
            continue
        identity_types = tuple(
            str(item).strip() for item in raw.get("identity_types") or () if str(item).strip()
        )
        policies.append(ProductSourcePolicy(
            provider_id, publishers, domains, max(0, max_age),
            identity_types or ProductSourcePolicy.allowed_identity_types,
        ))
    return tuple(policies)


class OfficialJsonProductProvider:
    """Connector for an operator-owned adapter over an official product source.

    The endpoint is optional and configured outside the repository. The adapter
    returns source-native identity and claims; the registry still validates the
    official publisher URL and exact product identity before accepting anything.
    """

    source_types = (
        "manufacturer_product_spec",
        "component_vendor_spec",
        "isv_compatibility",
    )

    def __init__(self, provider_id: str, *, endpoint: str, client: Any = None) -> None:
        self.provider_id = str(provider_id)
        self.endpoint = str(endpoint or "").strip()
        self._client = client

    def resolve(
        self,
        identity: ProductIdentity,
        *,
        claim_keys: tuple[str, ...],
        allow_live: bool,
    ) -> Optional[ProductCapabilityEvidence]:
        if not allow_live or not self.endpoint:
            return None
        from src.app.security.url_guard import validate_outbound_url

        allowed, reason = validate_outbound_url(self.endpoint)
        if not allowed:
            raise ValueError(f"product_capability_endpoint_blocked:{reason}")
        client = self._client
        if client is None:
            import httpx
            client = httpx
        response = client.get(
            self.endpoint,
            params={
                "identifier_type": identity.identifier_type,
                "identifier": identity.identifier,
                "claim_keys": ",".join(claim_keys),
            },
            timeout=3.0,
            follow_redirects=False,
            headers={"User-Agent": "ShopSquire-Product-Capability/1.0"},
        )
        response.raise_for_status()
        body = bytes(response.content)
        if len(body) > 512 * 1024:
            raise ValueError("product_capability_response_too_large")
        raw = json.loads(body)
        if not isinstance(raw, Mapping) or not raw:
            return None
        raw_identity = raw.get("identity") if isinstance(raw.get("identity"), Mapping) else {}
        return ProductCapabilityEvidence(
            provider_id=self.provider_id,
            source_type=str(raw.get("source_type") or "manufacturer_product_spec"),
            publisher=str(raw.get("publisher") or ""),
            source_url=str(raw.get("source_url") or ""),
            source_record_id=str(raw.get("source_record_id") or ""),
            retrieved_at=str(raw.get("retrieved_at") or ""),
            identity=ProductIdentity(
                sku=str(raw_identity.get("sku") or ""),
                identifier_type=str(raw_identity.get("identifier_type") or ""),
                identifier=str(raw_identity.get("identifier") or ""),
                configuration_hash=str(raw_identity.get("configuration_hash") or ""),
                form_factor=str(raw_identity.get("form_factor") or "unknown"),
            ),
            claims=tuple(item for item in list(raw.get("claims") or [])[:64] if isinstance(item, Mapping)),
            provenance_chain=tuple(str(item) for item in list(raw.get("provenance_chain") or [])[:16]),
            parser_id=str(raw.get("parser_id") or "operator_json_v1"),
            http_status=int(getattr(response, "status_code", 200)),
            response_body_sha256=hashlib.sha256(body).hexdigest(),
        )


class AsusOfficialHtmlProductProvider:
    """Source-specific parser for an exact SKU column on an ASUS/ROG spec page."""

    source_types = ("manufacturer_product_spec",)

    def __init__(self, provider_id: str, *, endpoint: str, client: Any = None) -> None:
        self.provider_id = str(provider_id)
        self.endpoint = str(endpoint or "").strip()
        self._client = client

    @staticmethod
    def _claim(attribute_key: str, value: Any, unit: str | None = None) -> dict[str, Any]:
        return {
            "attribute_key": attribute_key,
            "value": value,
            "unit": unit,
            "confidence": 1.0,
            "claim_class": "attested",
            "scope_caveat": "Exact ASUS SKU column on the official regional specification page.",
        }

    def resolve(
        self,
        identity: ProductIdentity,
        *,
        claim_keys: tuple[str, ...],
        allow_live: bool,
    ) -> Optional[ProductCapabilityEvidence]:
        if not allow_live or not self.endpoint:
            return None
        if identity.identifier_type != "manufacturer_part_number" or not identity.identifier:
            return None
        from src.app.security.url_guard import validate_outbound_url

        allowed, reason = validate_outbound_url(self.endpoint)
        if not allowed:
            raise ValueError(f"product_capability_endpoint_blocked:{reason}")
        client = self._client
        if client is None:
            import httpx
            client = httpx
        response = client.get(
            self.endpoint,
            timeout=6.0,
            follow_redirects=False,
            headers={"User-Agent": "ShopSquire-Product-Capability/1.0"},
        )
        response.raise_for_status()
        body = bytes(response.content)
        if len(body) > 1024 * 1024:
            raise ValueError("product_capability_response_too_large")
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
        sku_nodes = [
            node.get_text(" ", strip=True)
            for node in soup.find_all("p", class_=lambda value: value and "specProductName" in str(value))
        ]
        sku_values = [value for value in sku_nodes if "-" in value and " " not in value]
        try:
            sku_index = sku_values.index(identity.identifier)
        except ValueError:
            return None

        sections: dict[str, str] = {}
        for row in soup.find_all("div", class_=lambda value: value and re.search(r"ProductSpec__row__", str(value))):
            heading = row.find("h2")
            if heading is None:
                continue
            items = row.find_all("div", class_=lambda value: value and "ProductSpec__rowItem__" in str(value))
            if sku_index < len(items):
                sections[heading.get_text(" ", strip=True).lower()] = items[sku_index].get_text(" ", strip=True)

        parsed: dict[str, tuple[Any, str | None]] = {}
        operating_system = sections.get("operating system", "")
        if operating_system:
            parsed["operating_system"] = (operating_system, None)
        processor = sections.get("processor", "")
        if processor:
            parsed["cpu_model"] = (processor, None)
        graphics = sections.get("graphics", "")
        if "GeForce RTX" in graphics:
            parsed["gpu_class"] = ("consumer_geforce", None)
        vram_match = re.search(r"\b(\d{1,3})\s*GB\s+GDDR", graphics, re.IGNORECASE)
        if vram_match:
            parsed["gpu_vram_gb"] = (int(vram_match.group(1)), "GB")
        memory = sections.get("memory", "")
        ram_match = re.search(r"\b(\d{1,3})\s*GB\b", memory, re.IGNORECASE)
        if ram_match:
            parsed["ram_gb"] = (int(ram_match.group(1)), "GB")
        ceiling_match = re.search(r"Max Capacity\s*:\s*(\d{1,3})\s*GB", memory, re.IGNORECASE)
        if ceiling_match:
            parsed["ram_ceiling_gb"] = (int(ceiling_match.group(1)), "GB")
        if re.search(r"no expansion possible", memory, re.IGNORECASE):
            parsed["ram_upgradeable"] = (False, None)
        storage = sections.get("storage", "")
        storage_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\b", storage, re.IGNORECASE)
        if storage_match:
            amount = float(storage_match.group(1))
            parsed["storage_gb"] = (int(amount * 1000) if storage_match.group(2).upper() == "TB" else int(amount), "GB")

        requested = set(claim_keys)
        claims = tuple(
            self._claim(key, value, unit)
            for key, (value, unit) in parsed.items()
            if key in requested
        )
        if not claims:
            return None
        digest = hashlib.sha256(body).hexdigest()
        return ProductCapabilityEvidence(
            provider_id=self.provider_id,
            source_type="manufacturer_product_spec",
            publisher="Republic of Gamers",
            source_url=self.endpoint,
            source_record_id=f"{identity.identifier}:{digest}",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            identity=identity,
            claims=claims,
            provenance_chain=(f"https_get_sha256:{digest}", f"exact_sku_column:{identity.identifier}"),
            parser_id="asus_official_spec_columns_v1",
            http_status=int(getattr(response, "status_code", 200)),
            response_body_sha256=digest,
        )


def configured_product_capability_registry() -> ProductCapabilityEvidenceRegistry:
    policies = load_product_source_policies()
    allowed_tenants = tuple(
        item.strip()
        for item in str(os.getenv("PRODUCT_CAPABILITY_TENANT_ALLOWLIST") or "").split(",")
        if item.strip()
    )
    providers: list[OfficialJsonProductProvider] = []
    for policy in policies:
        env_key = "PRODUCT_CAPABILITY_" + "".join(
            char if char.isalnum() else "_" for char in policy.provider_id.upper()
        ) + "_URL"
        endpoint = str(os.getenv(env_key) or "").strip()
        if endpoint and allowed_tenants:
            source_format = str(os.getenv(env_key.removesuffix("_URL") + "_FORMAT") or "json").strip().lower()
            if source_format == "asus_html":
                providers.append(AsusOfficialHtmlProductProvider(policy.provider_id, endpoint=endpoint))
            else:
                providers.append(OfficialJsonProductProvider(policy.provider_id, endpoint=endpoint))
    return ProductCapabilityEvidenceRegistry(
        providers=providers,
        policies=policies,
        allowed_tenants=allowed_tenants or ("__not_configured__",),
    )


def identity_from_catalog_variant(variant: Any) -> ProductIdentity:
    """Choose the strongest externally resolvable identity without guessing."""
    specs = getattr(variant, "specs", None)
    specs = specs if isinstance(specs, Mapping) else {}
    from src.app.services.recommendation_core.workload_decision import configuration_hash

    raw_form_factor = str(
        specs.get("form_factor") or specs.get("computer_type") or specs.get("product_type") or ""
    ).strip().lower()
    title_low = str(getattr(variant, "title", "") or "").lower()
    if raw_form_factor in {"notebook", "mobile workstation"} or "laptop" in title_low:
        form_factor = "laptop"
    elif raw_form_factor in {"desktop", "workstation"} or "desktop" in title_low:
        form_factor = "desktop"
    elif raw_form_factor == "server" or "server" in title_low:
        form_factor = "server"
    else:
        form_factor = "unknown"
    config_hash = configuration_hash(
        sku=str(getattr(variant, "sku", "") or ""),
        specs=specs,
        form_factor=form_factor,
    )
    candidates = (
        ("machine_type_model", specs.get("machine_type_model") or specs.get("mtm")),
        ("manufacturer_part_number", specs.get("manufacturer_part_number") or specs.get("mpn")),
        ("gtin", specs.get("gtin") or specs.get("barcode") or specs.get("ean") or specs.get("upc")),
        ("family_identifier", specs.get("family_identifier") or specs.get("product_family") or specs.get("family")),
        ("model", specs.get("model") or specs.get("model_number")),
        ("title", getattr(variant, "title", "")),
    )
    for identifier_type, value in candidates:
        if str(value or "").strip():
            return ProductIdentity(
                sku=str(getattr(variant, "sku", "") or ""),
                identifier_type=identifier_type,
                identifier=str(value).strip(),
                configuration_hash=config_hash,
                form_factor=form_factor,
            )
    return ProductIdentity(
        sku=str(getattr(variant, "sku", "") or ""),
        identifier_type="unresolved",
        identifier="",
        configuration_hash=config_hash,
        form_factor=form_factor,
    )
