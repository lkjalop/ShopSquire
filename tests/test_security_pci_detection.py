from src.app.security.observer import analyze_payload


def test_pci_detection_triggers_llm06():
    payload = {"query": "My card is 4111 1111 1111 1111 please store it"}
    result = analyze_payload(payload)
    details = result.get("details", {})
    tags = details.get("owasp_llm_top10", [])
    signals = details.get("signals", {})
    assert signals.get("pci") is True
    assert "LLM06:SensitiveInformationDisclosure" in tags
