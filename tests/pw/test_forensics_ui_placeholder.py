def test_forensics_ui_route(page, test_server):
    base = test_server["base_url"]
    page.goto(base + "/ui/forensics")
    page.wait_for_selector("h1")
    heading = page.text_content("h1") or ""
    assert "Forensics Console" in heading
    status = page.text_content("#forensics-status") or ""
    assert "decision-trace" in status.lower()
