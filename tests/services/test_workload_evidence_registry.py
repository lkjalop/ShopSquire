from src.app.services.connectors.workload_evidence import (
    WorkloadEvidence,
    WorkloadEvidenceRegistry,
    WorkloadTarget,
)


class _Provider:
    provider_id = "official_vendor"
    supported_kinds = ("software",)

    def resolve(self, name: str, *, allow_live: bool):
        return WorkloadEvidence(
            kind="software", requested_name=name, resolved_name=name,
            provider_id=self.provider_id, status="resolved",
            minimum={"ram_gb": 16}, recommended={"ram_gb": 32},
            requested_target=WorkloadTarget(
                resolution="4k", fps=60, ray_tracing=True,
                api_compatibility=("vulkan",), architecture_compatibility=("cuda",),
            ),
            source_url="https://vendor.example/requirements",
            retrieved_at="2026-07-26T00:00:00Z", confidence=0.95,
            provenance_chain=("provider:official_vendor", "record:req-1"),
        )


def test_registry_resolves_typed_provider_evidence():
    registry = WorkloadEvidenceRegistry([_Provider()])

    result = registry.resolve("software", "Renderer X", allow_live=True)

    assert result is not None
    assert result.minimum["ram_gb"] == 16
    assert result.recommended["ram_gb"] == 32
    assert result.requested_target.resolution == "4k"
    assert result.requested_target.ray_tracing is True
    assert result.provenance_chain[-1] == "record:req-1"


def test_registry_obeys_provider_allowlist():
    registry = WorkloadEvidenceRegistry([_Provider()])

    result = registry.resolve(
        "software", "Renderer X", allow_live=True,
        provider_allowed=lambda provider_id: provider_id != "official_vendor",
    )

    assert result is None


def test_registry_records_provider_coverage_without_exposing_internal_state():
    registry = WorkloadEvidenceRegistry([_Provider()])

    result, attempts = registry.resolve_with_trace(
        "software", "Renderer X", allow_live=True,
    )

    assert result is not None
    assert attempts == [{
        "provider_id": "official_vendor",
        "status": "resolved",
        "allow_live": True,
        "source_record_id": None,
    }]


def test_registry_reports_when_no_provider_supports_the_workload_kind():
    registry = WorkloadEvidenceRegistry([_Provider()])

    result, attempts = registry.resolve_with_trace(
        "game", "Unknown Game", allow_live=True,
    )

    assert result is None
    assert attempts == []


def test_registry_lists_kind_coverage_without_claiming_provider_readiness():
    registry = WorkloadEvidenceRegistry([_Provider()])

    assert registry.provider_ids_for("software") == ("official_vendor",)
    assert registry.provider_ids_for("game") == ()


def test_offline_recognition_never_enables_live_provider_access():
    calls = []

    class _OfflineProvider(_Provider):
        def resolve(self, name: str, *, allow_live: bool):
            calls.append((name, allow_live))
            return super().resolve(name, allow_live=allow_live) if name == "Renderer X" else None

    registry = WorkloadEvidenceRegistry([_OfflineProvider()])

    assert registry.recognizes_offline("Renderer X") is True
    assert registry.recognizes_offline("unknown workload") is False
    assert calls == [("Renderer X", False), ("unknown workload", False)]
