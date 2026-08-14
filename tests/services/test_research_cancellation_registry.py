from src.app.services.research_cancellation_registry import ResearchCancellationRegistry


def test_cancellation_is_scoped_to_exact_tenant_case_and_execution() -> None:
    registry = ResearchCancellationRegistry()
    registry.register("tenant-a", "case-a", "execution-a")

    assert not registry.cancelled("tenant-a", "case-a", "execution-a")
    assert registry.cancel("tenant-b", "case-a", "execution-a", "buyer_departed")
    assert registry.cancelled("tenant-b", "case-a", "execution-a")
    assert registry.cancel("tenant-a", "case-a", "execution-a", "buyer_departed")
    assert registry.cancelled("tenant-a", "case-a", "execution-a")
    assert not registry.cancelled("tenant-a", "case-a", "execution-b")


def test_cancellation_arriving_before_registration_is_not_lost() -> None:
    registry = ResearchCancellationRegistry()

    assert registry.cancel("tenant-a", "case-a", "execution-a", "buyer_departed")
    registry.register("tenant-a", "case-a", "execution-a")

    assert registry.cancelled("tenant-a", "case-a", "execution-a")
