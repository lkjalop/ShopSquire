import base64
import os
from pathlib import Path
from playwright.sync_api import sync_playwright


OUT_DIR = Path("runs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQI12P4"
    "//8/AwAI/AL+J6sE9QAAAABJRU5ErkJggg=="
)


def main():
    img_path = OUT_DIR / "cv_upload.png"
    img_path.write_bytes(base64.b64decode(TINY_PNG_B64))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE, timeout=30000)
        page.wait_for_timeout(4000)

        # Open assistant (try title or CTA via DOM)
        try:
            page.wait_for_selector("button", timeout=10000)
            page.evaluate(
                "() => {"
                "const btn = document.querySelector(\"button[title='Open assistant']\") || "
                "Array.from(document.querySelectorAll('button')).find(b => (b.textContent || '').includes('Assistant')) || "
                "Array.from(document.querySelectorAll('button')).find(b => (b.textContent || '').includes('Need help')) || "
                "Array.from(document.querySelectorAll('button')).find(b => (b.getAttribute('title') || '').includes('assistant'));"
                "if (btn) { btn.click(); return true; } return false;"
                "}"
            )
        except Exception:
            pass
        page.wait_for_timeout(1200)
        if not page.locator("text=ShopSquire Assistant").is_visible():
            out0 = OUT_DIR / "00_landing.png"
            out_html = OUT_DIR / "00_landing.html"
            page.screenshot(path=str(out0), full_page=True)
            out_html.write_text(page.content(), encoding="utf-8")
            raise RuntimeError("Unable to open assistant overlay; saved 00_landing.png/html")
        page.wait_for_selector("text=ShopSquire Assistant", timeout=10000)

        # Upload image via hidden input
        file_input = page.locator("input[type='file']")
        file_input.set_input_files(str(img_path))
        page.wait_for_timeout(300)

        # Send complaint message
        page.get_by_placeholder("Ask me anything about products, orders, or help...").fill(
            "chargeback if no refund. fake product. manual review please"
        )
        page.keyboard.press("Enter")
        page.wait_for_timeout(2000)

        out1 = OUT_DIR / "07_cv_escalation.png"
        page.screenshot(path=str(out1), full_page=True)

        # Open decision trace
        page.get_by_title("Decision & Security Trace").click()
        page.wait_for_timeout(2000)

        out2 = OUT_DIR / "08_trace_evidence.png"
        page.screenshot(path=str(out2), full_page=True)

        browser.close()
        print("wrote", out1, out2)


if __name__ == "__main__":
    main()
