"""
Comprehensive Playwright test: gaming laptop query + dual image upload
Tests:
  - CV relevance detection (red apple fruit vs gaming laptop query)
  - QR code decode from MSI laptop image (MSI-SSN.png)
  - Product recommendation quality + why
  - Security matrix (MITRE/OWASP tags)
  - Parallel agent trace (CV triage, NLP, fraud, inventory)
  - Security gate decision
  - LLM response quality (yes/no budget, specs cited)
  - qwen3:30b model routing verification

UI NOTE: Chat panel opens via "Ask Me!" FAB. Messages are in styles.chatPanel.
  Selectors: [class*="messageContent"] for message text,
             textarea[placeholder*="message"] for composer,
             AttachmentButton has 2 hidden file inputs: .nth(0)=camera .nth(1)=file-upload
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

# -- Config -------------------------------------------------------------------
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")
API_BASE     = os.getenv("API_BASE",     "http://127.0.0.1:8080")
API_KEY      = os.getenv("MERCHANT_API_KEY", "local-merchant-key")
OUT          = Path("runs/pw_gaming_multiimage"); OUT.mkdir(parents=True, exist_ok=True)

APPLE_IMG  = Path("dump/test-cv/apple-red.jpg")
MSI_IMG    = Path("tmp_ui_uploads/msi-SSN.png")
QUERY      = "I am looking for a laptop for gaming. My budget is $1200 to $1800."
SESSION_ID = f"pw-{uuid.uuid4().hex[:8]}"   # fresh per run — no Redis cache hit
UID        = f"pw-user-{uuid.uuid4().hex[:6]}"

LLM_WAIT_MS   = 120_000  # 120s — qwen3:30b at 30B is slow on first call
SHORT_WAIT_MS = 3_000

# -- Helpers ------------------------------------------------------------------

def shot(page: Page, name: str) -> Path:
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=True)
    print(f"  [screenshot] {p}")
    return p


def save_json(name: str, data: dict) -> None:
    p = OUT / f"{name}.json"
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"  [saved] {p}")


def open_chat(page: Page) -> None:
    """Click the Ask Me! FAB and wait for the chat panel to appear."""
    fab = page.locator('[class*="chatFab"], [class*="fab"]').first
    if fab.count() == 0:
        fab = page.get_by_role("button", name="Ask Me!")
    fab.click()
    # Chat panel is visible when class*="chatPanel" is in DOM
    page.wait_for_selector('[class*="chatPanel"], [class*="chatTitle"]', timeout=8_000)
    page.wait_for_timeout(600)


def send_message(page: Page, text: str) -> None:
    """Type into the chat composer textarea and submit."""
    ta = page.locator('textarea[placeholder*="message"], textarea[placeholder*="Type"]').first
    ta.fill(text)
    page.keyboard.press("Enter")


def upload_file(page: Page, file_path: Path) -> None:
    """
    Attach an image via the AttachmentButton.
    The button shows a menu with Camera / Upload File / Paste.
    We click the '+' attach button, then pick 'Upload File',
    which triggers the second hidden file input (.nth(1)).
    Fallback: directly set files on the hidden file input.
    """
    try:
        # Method A: interact with the menu
        attach_btn = page.locator('[aria-label="Attach image"], [title="Attach image"]').first
        attach_btn.click(timeout=3_000)
        page.wait_for_timeout(400)
        # Menu should appear — click "Upload File"
        upload_item = page.get_by_role("menuitem", name="Upload File")
        if upload_item.count() == 0:
            upload_item = page.get_by_text("Upload File")
        if upload_item.count() > 0:
            with page.expect_file_chooser() as fc_info:
                upload_item.first.click()
            fc_info.value.set_files(str(file_path))
            page.wait_for_timeout(600)
            return
    except Exception as e:
        print(f"  [upload menu failed: {e}] falling back to direct input")

    # Method B: set files directly on the file-upload hidden input (not camera)
    inputs = page.locator("input[type='file']")
    # First input is camera (capture="environment"), second is file upload
    target = inputs.nth(1) if inputs.count() >= 2 else inputs.first
    target.set_input_files(str(file_path))
    page.wait_for_timeout(600)


def wait_for_response(page: Page, prev_count: int = 0, timeout_ms: int = LLM_WAIT_MS) -> str:
    """
    Poll until a new assistant message appears beyond prev_count.
    Uses [class*="messageContent"] which matches CSS module mangled names like
    App_messageContent__AbCdE.
    """
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        # CSS module class contains "messageContent" as substring
        msgs = page.locator('[class*="messageContent"]')
        count = msgs.count()
        if count > prev_count:
            # Wait a moment for text to fully render
            page.wait_for_timeout(1_000)
            msgs = page.locator('[class*="messageContent"]')
            txt = msgs.last.inner_text().strip()
            if len(txt) > 10:
                return txt
        page.wait_for_timeout(2_000)
    # Fallback: grab the last messageContent element
    try:
        return page.locator('[class*="messageContent"]').last.inner_text().strip()
    except Exception:
        return ""


def count_messages(page: Page) -> int:
    return page.locator('[class*="messageContent"]').count()


def open_trace(page: Page) -> None:
    """Open the Decision Trace drawer via the gear icon."""
    for selector in [
        '[aria-label="Decision Trace"]',
        'button[title*="Decision Trace"]',
        'button[title*="Trace"]',
        '[class*="traceBtn"]',
    ]:
        try:
            btn = page.locator(selector).first
            if btn.count() > 0:
                btn.click()
                page.wait_for_timeout(1_500)
                return
        except Exception:
            pass


def click_tab(page: Page, *names: str) -> bool:
    for n in names:
        for role in ("button", "tab"):
            try:
                btn = page.get_by_role(role, name=n)
                if btn.count() > 0:
                    btn.first.click()
                    page.wait_for_timeout(1_200)
                    return True
            except Exception:
                pass
        try:
            txt = page.get_by_text(n, exact=False)
            if txt.count() > 0:
                txt.first.click()
                page.wait_for_timeout(1_200)
                return True
        except Exception:
            pass
    return False


# -- Direct API probe ---------------------------------------------------------

def api_probe_recommend(query: str, msi_b64: str, uid: str, session_id: str) -> dict:
    """Hit /api/v1/chat/query directly — fresh session to avoid Redis cache."""
    import urllib.request
    payload = json.dumps({
        "query": query,
        "uid": uid,
        "session_id": session_id,
        "image_b64": msi_b64,
        "image_mime": "image/png",
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/api/v1/chat/query",
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def api_probe_cv(img_path: Path, mime: str) -> dict:
    """Hit /api/v1/cv/analyze with one image to get raw CV signals."""
    import urllib.request, base64
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    payload = json.dumps({"image_b64": b64, "mime_type": mime, "context": "product_query"}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/api/v1/cv/analyze",
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


# -- MAIN TEST ----------------------------------------------------------------

def main() -> None:
    results: dict = {
        "query": QUERY,
        "session_id": SESSION_ID,
        "images_used": [str(APPLE_IMG), str(MSI_IMG)],
        "api_probe_cv_apple": {},
        "api_probe_cv_msi": {},
        "api_probe_recommend": {},
        "ui": {},
        "findings": [],
        "issues": [],
    }

    # -- 1. CV triage: apple ------------------------------------------------
    print("\n=== Step 1: CV API — apple image ===")
    cv_apple = api_probe_cv(APPLE_IMG, "image/jpeg")
    results["api_probe_cv_apple"] = cv_apple
    save_json("01_cv_apple", cv_apple)
    apple_labels = str(cv_apple).lower()
    apple_flagged = any(w in apple_labels for w in (
        "food", "fruit", "produce", "irrelevant", "mismatch", "not_laptop", "rejected", "apple"
    ))
    print(f"  raw_labels: {cv_apple.get('cv_analysis',{}).get('raw_labels',[])}")
    print(f"  category: {cv_apple.get('cv_analysis',{}).get('damage_type','?')}")
    print(f"  flagged: {apple_flagged}")

    if apple_flagged:
        results["findings"].append("PASS: Apple (fruit) image flagged as non-electronics")
    else:
        results["issues"].append("FAIL: Apple fruit image NOT detected as wrong category")

    # -- 1b. CV triage: MSI ------------------------------------------------
    print("\n=== Step 1b: CV API — MSI laptop image ===")
    cv_msi = api_probe_cv(MSI_IMG, "image/png")
    results["api_probe_cv_msi"] = cv_msi
    save_json("01_cv_msi", cv_msi)
    msi_qr   = str(cv_msi.get("qr_codes", cv_msi.get("qr_decoded", ""))).strip()
    msi_text = str(cv_msi.get("cv_analysis", {}).get("extracted_text", "")).strip()
    msi_labels = str(cv_msi.get("cv_analysis", {}).get("raw_labels", [])).lower()
    print(f"  qr_codes: {cv_msi.get('qr_codes', [])}")
    print(f"  extracted_text: {msi_text[:80]!r}")
    print(f"  raw_labels: {msi_labels[:80]}")

    if msi_qr or msi_text or "laptop" in msi_labels or "msi" in msi_labels:
        results["findings"].append(f"PASS: MSI image CV extracted data: qr={msi_qr[:60]!r} text={msi_text[:40]!r}")
    else:
        results["issues"].append("FAIL: MSI image CV returned no QR/text/labels — pyzbar/tesseract not running")

    # -- 2. Recommend probe (fresh session) ----------------------------------
    print(f"\n=== Step 2: API recommend probe (session={SESSION_ID}) ===")
    import base64
    msi_b64   = base64.b64encode(MSI_IMG.read_bytes()).decode()
    apple_b64 = base64.b64encode(APPLE_IMG.read_bytes()).decode()
    print("  Calling /api/v1/chat/query (may take 60-120s for qwen3:30b)...")
    rec = api_probe_recommend(QUERY, msi_b64, UID, SESSION_ID)
    results["api_probe_recommend"] = rec
    save_json("02_recommend", rec)

    rec_products  = rec.get("results", rec.get("products", []))
    rec_message   = str(rec.get("message", rec.get("assistant_message", rec.get("response", ""))))
    rec_nqe       = rec.get("next_questions", [])
    rec_security  = rec.get("security", rec.get("security_analysis", {}))
    rec_agents    = rec.get("agent_trace", rec.get("agents", rec.get("trace_events", [])))
    rec_budget    = rec.get("constraints", {}).get("budget_max")
    rec_model     = rec.get("model_used", rec.get("llm_model", "?"))
    rec_complexity= rec.get("complexity_score", rec.get("complexity", {}))
    rec_score     = rec_complexity.get("score") if isinstance(rec_complexity, dict) else rec_complexity

    print(f"  model_used:  {rec_model}")
    print(f"  complexity:  score={rec_score}  tier={rec_complexity.get('tier','?') if isinstance(rec_complexity,dict) else '?'}")
    print(f"  budget_max:  {rec_budget}")
    print(f"  products:    {len(rec_products)}")
    print(f"  message:     {rec_message[:200]!r}")
    print(f"  NQE:         {[q.get('text') for q in rec_nqe[:3]]}")

    # Routing check: gaming + image should hit qwen3:30b
    if "30b" in str(rec_model).lower() or "expert" in str(rec_model).lower():
        results["findings"].append(f"PASS: Routed to qwen3:30b ({rec_model}) — score={rec_score}")
    elif "14b" in str(rec_model).lower() or "medium" in str(rec_model).lower():
        results["issues"].append(f"WARN: Routed to medium model ({rec_model}) score={rec_score} — expected large for gaming+image")
    else:
        results["issues"].append(f"FAIL: Wrong model: {rec_model!r} score={rec_score} — expected qwen3:30b")

    # Budget extraction
    if rec_budget and rec_budget >= 1200:
        results["findings"].append(f"PASS: Budget extracted: max={rec_budget}")
    else:
        results["issues"].append(f"FAIL: Budget not extracted (budget_max={rec_budget}) — parser missed '$1200 to $1800'")

    # Products
    if rec_products:
        results["findings"].append(f"PASS: {len(rec_products)} products returned")
        for p in rec_products[:5]:
            name  = p.get("name", "?")
            price = int(p.get("price_cents", 0) or 0) // 100
            specs = p.get("specs", {})
            gpu   = specs.get("gpu_model", specs.get("gpu_vram_gb", "no-GPU"))
            ram   = specs.get("ram_gb", "?")
            print(f"    {name} — ${price}  GPU:{gpu} RAM:{ram}GB")
        prices = [int(p.get("price_cents", 0) or 0) // 100 for p in rec_products if p.get("price_cents")]
        in_budget = [p for p in prices if 1000 <= p <= 2200]
        if prices and len(in_budget) >= len(prices) * 0.5:
            results["findings"].append(f"PASS: Prices roughly in budget: {prices}")
        else:
            results["issues"].append(f"FAIL: Budget filter not applied — prices={prices}, in_budget={in_budget}")
        # Gaming GPU check
        has_rtx = any("rtx" in str(p.get("specs","")).lower() or "rtx" in str(p.get("name","")).lower()
                      for p in rec_products)
        if has_rtx:
            results["findings"].append("PASS: At least one RTX GPU product in results")
        else:
            results["issues"].append("FAIL: No RTX gaming laptops returned — catalog missing gaming products with GPU specs")
    else:
        results["issues"].append("FAIL: No products returned (LLM may have timed out on qwen3:30b)")

    # LLM message quality
    msg_low = rec_message.lower()
    if any(w in msg_low for w in ("rtx", "gpu", "gaming", "performance", "1200", "1800", "budget")):
        results["findings"].append(f"PASS: LLM message mentions gaming/GPU/budget: {rec_message[:120]!r}")
    elif len(rec_message) > 30:
        results["issues"].append(f"WARN: LLM message generic (no gaming/GPU refs): {rec_message[:120]!r}")
    else:
        results["issues"].append(f"FAIL: LLM message empty or too short: {rec_message[:120]!r}")

    # Agent trace
    if rec_agents:
        names = [a.get("agent_name", a.get("source_id", "?")) for a in
                 (rec_agents if isinstance(rec_agents, list) else [])]
        results["findings"].append(f"INFO: Agents in trace: {names[:8]}")

    # -- 3. Playwright UI test -----------------------------------------------
    print("\n=== Step 3: Playwright UI test ===")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()

        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(f"[{m.type}] {m.text}")
                if m.type in ("error", "warning") else None)

        print("  Loading frontend...")
        page.goto(FRONTEND_URL, timeout=25_000)
        page.wait_for_timeout(2_000)
        shot(page, "00_landing")

        # -- 3a. Open chat panel
        print("  Opening chat panel (Ask Me!)...")
        open_chat(page)
        shot(page, "01_chat_open")
        results["ui"]["chat_opened"] = True

        msg_count_before = count_messages(page)
        print(f"  Initial message count: {msg_count_before}")

        # -- 3b. Upload apple image
        print(f"  Uploading apple image: {APPLE_IMG}")
        upload_file(page, APPLE_IMG)
        page.wait_for_timeout(500)
        shot(page, "02_apple_uploaded")

        # -- 3c. Send gaming query
        print(f"  Sending query: {QUERY!r}")
        send_message(page, QUERY)
        shot(page, "03_query_sent")

        # -- 3d. Wait for LLM response
        print(f"  Waiting up to {LLM_WAIT_MS//1000}s for qwen3:30b response...")
        response_text = wait_for_response(page, prev_count=msg_count_before + 1, timeout_ms=LLM_WAIT_MS)
        shot(page, "04_response_apple_query")
        results["ui"]["response_apple_query"] = response_text
        print(f"  Response: {response_text[:250]!r}")

        resp_low = response_text.lower()
        if any(w in resp_low for w in ("fruit", "food", "apple", "not a laptop", "image shows", "irrelevant", "photo shows")):
            results["findings"].append(f"PASS UI: Apple image flagged in LLM response")
        else:
            results["issues"].append(f"WARN UI: Apple image not explicitly mentioned in response")

        if any(w in resp_low for w in ("rtx", "gpu", "gaming", "1200", "1800", "$", "budget")):
            results["findings"].append(f"PASS UI: Response cites gaming/budget context")
        elif len(response_text) > 50:
            results["issues"].append(f"WARN UI: Response generic, no gaming/budget context: {response_text[:100]!r}")
        else:
            results["issues"].append(f"FAIL UI: Response empty — LLM timed out or selectors wrong")

        msg_count_after_q1 = count_messages(page)

        # -- 3e. Upload MSI image + follow-up
        print(f"  Uploading MSI image: {MSI_IMG}")
        upload_file(page, MSI_IMG)
        page.wait_for_timeout(500)
        send_message(page, "This is the MSI laptop I'm comparing. Find me something similar or better within my $1200-$1800 budget.")
        shot(page, "05_msi_query_sent")

        print("  Waiting for MSI follow-up response...")
        msi_response = wait_for_response(page, prev_count=msg_count_after_q1 + 1, timeout_ms=LLM_WAIT_MS)
        shot(page, "06_response_msi_query")
        results["ui"]["response_msi_query"] = msi_response
        print(f"  MSI response: {msi_response[:250]!r}")

        if any(w in msi_response.lower() for w in ("msi", "rtx", "gaming", "budget", "similar", "1200", "1800")):
            results["findings"].append(f"PASS UI: MSI follow-up cites gaming/budget")
        else:
            results["issues"].append(f"WARN UI: MSI follow-up generic: {msi_response[:100]!r}")

        # -- 3f. Open Decision Trace
        print("  Opening Decision Trace...")
        open_trace(page)
        page.wait_for_timeout(2_000)
        shot(page, "07_trace_overview")
        trace_html = page.content()
        results["ui"]["trace_opened"] = (
            "trace" in trace_html.lower() or "decision" in trace_html.lower()
        )

        # -- 3g. Security Matrix tab
        print("  Clicking Security Matrix tab...")
        click_tab(page, "Security Matrix", "Security", "Matrix")
        page.wait_for_timeout(1_500)
        shot(page, "08_security_matrix")
        sec_html = page.content()

        mitre_present = "MITRE:" in sec_html or "mitre" in sec_html.lower()
        owasp_present = "OWASP:" in sec_html or "owasp" in sec_html.lower()
        qr_in_matrix  = any(w in sec_html.lower() for w in ("qr", "barcode", "malicious_url"))
        steg_in_matrix = any(w in sec_html.lower() for w in ("steg", "lsb", "steganograph"))

        results["ui"]["security_matrix"] = {
            "mitre_present": mitre_present,
            "owasp_present": owasp_present,
            "qr_signal": qr_in_matrix,
            "steg_signal": steg_in_matrix,
        }
        for flag, label in [(mitre_present, "MITRE tags"), (owasp_present, "OWASP tags"),
                             (qr_in_matrix, "QR signal"), (steg_in_matrix, "Steg signal")]:
            if flag:
                results["findings"].append(f"PASS: {label} in Security Matrix")
            else:
                results["issues"].append(f"WARN: {label} not visible in Security Matrix")

        # -- 3h. Agent Events tab
        print("  Clicking Agent Events tab...")
        click_tab(page, "Agent Events", "Events", "Agents", "Timeline")
        page.wait_for_timeout(1_500)
        shot(page, "09_agent_events")
        events_html = page.content()

        agents_fired = {
            "CV_triage":        any(w in events_html.lower() for w in ("cv_triage", "cv triage", "computer_vision")),
            "NLP_search":       any(w in events_html.lower() for w in ("nlp_search", "nlp search", "candidate_retrieval")),
            "Fraud_scoring":    any(w in events_html.lower() for w in ("fraud_scor", "fraud score")),
            "Inventory":        any(w in events_html.lower() for w in ("inventory", "inventory_agent")),
            "Policy_gate":      any(w in events_html.lower() for w in ("policy_gate", "policy gate")),
            "Vision_reasoning": any(w in events_html.lower() for w in ("vision_reasoning", "visionreasoning")),
            "NQE":              any(w in events_html.lower() for w in ("nqe", "next_question")),
        }
        results["ui"]["agents_fired"] = agents_fired
        for agent, fired in agents_fired.items():
            (results["findings"] if fired else results["issues"]).append(
                f"{'PASS' if fired else 'WARN'}: {agent} {'in trace' if fired else 'NOT in trace'}"
            )

        # -- 3i. Why Recommended tab
        print("  Clicking Why Recommended tab...")
        click_tab(page, "Why Recommended", "Why", "Explanation", "Reasoning")
        page.wait_for_timeout(1_500)
        shot(page, "10_why_recommended")
        why_html = page.content()
        results["ui"]["why_has_content"] = len(why_html) > 2000

        # -- 3j. Complexity badge visible?
        complexity_badge = page.locator('[class*="complexityBadge"]')
        if complexity_badge.count() > 0:
            badge_text = complexity_badge.first.inner_text()
            results["ui"]["complexity_badge"] = badge_text
            results["findings"].append(f"PASS: Complexity badge visible: {badge_text!r}")
        else:
            results["issues"].append("WARN: No complexity badge visible in chat")

        # -- Console errors
        results["ui"]["console_errors"] = console_errors[:20]
        if console_errors:
            print(f"  WARN: {len(console_errors)} console errors captured")

        shot(page, "11_final_state")
        ctx.close()
        browser.close()

    # -- 4. Print report -------------------------------------------------------
    save_json("REPORT", results)

    print("\n" + "=" * 72)
    print("SHOPSQUIRE GAMING MULTIIMAGE TEST — qwen3:30b + qwen3-vl:30b")
    print("=" * 72)
    print(f"\nSession: {SESSION_ID}  UID: {UID}")
    print(f"Query:   {QUERY}")
    print(f"Images:  apple-red.jpg (fruit), msi-SSN.png (gaming laptop + QR)")
    print(f"\nAPI Recommend:")
    print(f"  Model:      {rec_model}")
    print(f"  Complexity: score={rec_score}")
    print(f"  Budget max: {rec_budget}")
    print(f"  Products ({len(rec_products)}):")
    for p in rec_products[:6]:
        name  = p.get("name", "?")
        price = int(p.get("price_cents", 0) or 0) // 100
        specs = p.get("specs", {})
        gpu   = specs.get("gpu_model", specs.get("gpu_vram_gb", "no-GPU"))
        print(f"    - {name} ${price}  GPU:{gpu}")
    print(f"\nLLM Response:\n  {rec_message[:400]}")
    print(f"\nNQE Questions:")
    for q in rec_nqe[:4]:
        print(f"  ? {q.get('text', q)}")
    print(f"\nSecurity Matrix: MITRE={mitre_present} OWASP={owasp_present} QR={qr_in_matrix}")
    print(f"Agents fired:    {agents_fired}")
    print(f"\nFindings ({len(results['findings'])}):")
    for f in results["findings"]:
        print(f"  {f}")
    print(f"\nIssues / Gaps ({len(results['issues'])}):")
    for i in results["issues"]:
        print(f"  {i}")
    print(f"\nScreenshots: {OUT}/")
    print(f"Full JSON:   {OUT}/REPORT.json")
    print("=" * 72)


if __name__ == "__main__":
    main()
