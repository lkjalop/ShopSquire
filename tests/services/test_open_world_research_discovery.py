from src.app.services.case_research_plan import build_case_research_plan
from src.app.services.open_world_research_discovery import discover_open_world_publishers


class StubFetcher:
    def __init__(self):
        self.last_receipt = {}
        self.calls = []

    def fetch(self, query, *, allowlist, timeout_s, discovery_candidates_only):
        self.calls.append((query, allowlist, timeout_s, discovery_candidates_only))
        self.last_receipt = {
            "query_hash": f"hash-{len(self.calls)}",
            "network_execution": True,
            "external_call_dispatched": True,
            "execution_status": "completed",
            "http_status": 200,
        }
        return [
            {"url": "https://vendor.example/blog/opinion", "title": "Opinion"},
            {"url": "https://vendor.example/docs/system-requirements/", "title": "System requirements"},
        ]


def test_novel_plan_runs_bounded_discovery_without_fetching_or_claiming_authority():
    plan = build_case_research_plan("novel scientific solver", allow_open_world=True)
    assert plan is not None
    fetcher = StubFetcher()
    result = discover_open_world_publishers(
        plan, search_url_template="http://localhost/search?q={query}", fetcher=fetcher,
    )
    assert len(fetcher.calls) == 3
    assert all(call[1] == [] and call[3] is True for call in fetcher.calls)
    assert result["candidates"][0]["url"].endswith("/docs/system-requirements/")
    assert all("/blog/" not in item["url"] for item in result["candidates"])
    assert result["provider_accounting"] == {
        "discovery_calls": 3, "external_calls": 3,
        "official_origin_fetches": 0, "paid_calls": 0,
    }
    assert result["claims"] == []
    assert all(item["authority"] == "not_accepted" for item in result["candidates"])
