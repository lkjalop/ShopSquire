import os

from src.app.services import email_providers as ep


def test_rewrite_safe_links_enabled(monkeypatch):
    os.environ["SAFE_LINK_REWRITE_ENABLED"] = "1"

    def _mk(**kwargs):
        return {"safe_url": f"https://safe.local/r/{kwargs.get('original_url', '').split('/')[-1]}"}

    monkeypatch.setattr(ep, "create_safe_link", _mk)
    out = ep._rewrite_safe_links(
        "Pay at https://billing.example.com/inv/123 now.",
        tenant_id="t1",
        campaign_id="camp1",
    )
    assert "safe.local" in out
    assert "billing.example.com" not in out

