import os

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from src.app.security.email_security_rules import extract_iocs


def test_ioc_extractor_urls_domains_ips():
    text = "Visit https://bad.example.com/login and 192.168.1.10; also bad.example.com"
    iocs = extract_iocs(text)
    types = {x["type"] for x in iocs}
    assert {"url", "domain", "ip"}.issubset(types)
