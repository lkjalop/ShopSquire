from src.app.services.publisher_origin_verification import verify_publisher_origin


def test_origin_consistency_uses_document_signals_not_workload_aliases():
    result = verify_publisher_origin(
        approved_url="https://docs.solver.example/requirements",
        purpose="coupled thermo-fluid simulation in Solver",
        content=b"""
          <html><head><title>Solver System Requirements</title>
          <link rel='canonical' href='https://docs.solver.example/requirements'>
          <meta property='og:site_name' content='Solver'></head>
          <body>Thermo-fluid simulation requirements and supported operating systems.</body></html>
        """,
    )
    assert result.status == "origin_consistent"
    assert result.ownership_authority == "not_independently_verified"
    assert "solver" in result.identity_host_overlap
    assert result.subject_overlap


def test_cross_origin_canonical_is_a_hard_contradiction():
    result = verify_publisher_origin(
        approved_url="https://lookalike.example/requirements",
        purpose="pathology image analysis",
        content=(
            "<html><head><link rel='canonical' "
            "href='https://actual-publisher.example/requirements'></head>"
            "<body>Pathology image analysis</body></html>"
        ),
    )
    assert result.status == "contradicted"
    assert result.canonical_origin_consistent is False


def test_missing_identity_stays_unresolved_not_verified_or_safe():
    result = verify_publisher_origin(
        approved_url="https://example.org/page",
        purpose="nanopore basecalling in the field",
        content="<html><body>Generic landing page.</body></html>",
    )
    assert result.status == "unresolved"
    assert result.ownership_authority == "not_independently_verified"
