import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import requests


OUT_DIR = Path("runs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PORT = os.getenv("PLAYWRIGHT_TEST_PORT", os.getenv("API_PORT", "8080"))
HOST = os.getenv("PLAYWRIGHT_TEST_HOST", "127.0.0.1")
WAIT_FOR_RESULTS = int(os.getenv("WAIT_FOR_RESULTS_TIMEOUT", "12"))
BASE = os.getenv("E2E_BASE_URL", f"http://{HOST}:{PORT}")

console_lines = []
page_errors = []


def save_console(fn: Path):
    fn.write_text("\n".join(console_lines + (['PAGE_ERRORS:'] + page_errors if page_errors else [])), encoding="utf-8")


def main():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.on("console", lambda msg: console_lines.append(f"CONSOLE {msg.type}: {msg.text}"))
            page.on("pageerror", lambda e: page_errors.append(str(e)))

            print("Opening storefront at", BASE + "/ui/storefront")
            resp = page.goto(BASE + "/ui/storefront", timeout=15000)
            print("status", getattr(resp, "status", None))
            page.wait_for_timeout(600)
            # 01 - collapsed storefront
            out1 = OUT_DIR / "01_storefront_collapsed.png"
            page.screenshot(path=str(out1), full_page=True)
            print("wrote", out1)

            # 02 - open widget (click fab inside shadow DOM)
            try:
                ok = page.evaluate("() => { const el=document.querySelector('shopsquire-widget'); if(!el) return 'noel'; const sr = el.shadowRoot; if(!sr) return 'noshadow'; const fab = sr.getElementById('fab'); if(!fab) return 'nofab'; fab.click(); return 'clicked'; }")
                print('widget click result', ok)
            except Exception as e:
                print('widget click failed', e)
            page.wait_for_timeout(500)
            out2 = OUT_DIR / "02_widget_open.png"
            page.screenshot(path=str(out2), full_page=True)
            print("wrote", out2)

            # 03 - submit a query to populate grid
            try:
                q = "Top 3 laptops 16GB RAM"
                page.evaluate(f"() => {{ const el=document.querySelector('shopsquire-widget'); if(!el) return 'noel'; const sr = el.shadowRoot; const inp = sr.getElementById('query'); if(inp) inp.value = '{q}'; const btn = sr.getElementById('send'); if(btn) btn.click(); return true; }}")
            except Exception as e:
                print('submit query failed', e)
            # Wait for results to appear in widget results container (configurable)
            try:
                page.wait_for_function(
                    "() => { const el = document.querySelector('shopsquire-widget'); if(!el) return false; const sr = el.shadowRoot; const r = sr && sr.querySelector('#results'); return r && r.innerHTML && r.innerHTML.length > 10; }",
                    timeout=WAIT_FOR_RESULTS * 1000,
                )
            except Exception:
                print('results did not appear (timeout)')
                # Fallback: inject demo results into widget so we can exercise grid/comparison flows
                try:
                    demo_js = (
                        "() => { const el = document.querySelector('shopsquire-widget'); if(!el) return 'noel';"
                        "el.state = el.state || {}; el.state.results = ["
                        "{ id: 'p-demo-1', name: 'Demo Laptop A', price: 1299, ram: 16, storage: '512GB', rating: 4.6, reasons: ['Demo reason A'] },"
                        "{ id: 'p-demo-2', name: 'Demo Laptop B', price: 1499, ram: 16, storage: '1TB', rating: 4.5, reasons: ['Demo reason B'] },"
                        "{ id: 'p-demo-3', name: 'Demo Laptop C', price: 1399, ram: 16, storage: '512GB', rating: 4.4, reasons: ['Demo reason C'] }"
                        "]; if(typeof el.render === 'function') el.render(); return true; }"
                    )
                    r = page.evaluate(demo_js)
                    print('injected demo results', r)
                except Exception as e:
                    print('inject demo results failed', e)
            page.wait_for_timeout(300)
            out3 = OUT_DIR / "03_results_grid.png"
            page.screenshot(path=str(out3), full_page=True)
            print("wrote", out3)

            # 04 - trigger comparison via compare button inside results
            try:
                page.evaluate("() => { const el=document.querySelector('shopsquire-widget'); const sr = el && el.shadowRoot; const c = sr && sr.querySelector('#results'); const cmpBtn = c && c.querySelector('[data-compare]'); if(cmpBtn) cmpBtn.click(); return true; }")
            except Exception as e:
                print('compare click failed', e)
            page.wait_for_timeout(500)
            out4 = OUT_DIR / "04_comparison.png"
            page.screenshot(path=str(out4), full_page=True)
            print("wrote", out4)

            # 05 - open a product detail and open Decision Trace gear modal
            try:
                # click first product detail link on storefront
                page.evaluate("() => { const d = document.querySelector('.detail'); if(d) d.click(); return true; }")
                page.wait_for_timeout(800)
                # click decision gear (either on detail page or global)
                page.evaluate("() => { const g = document.querySelector('[data-test=\"decision-gear\"]') || document.getElementById('decision-gear'); if(g) g.click(); return true; }")
            except Exception as e:
                print('detail or decision gear click failed', e)
            page.wait_for_timeout(600)
            out5 = OUT_DIR / "05_decision_trace.png"
            page.screenshot(path=str(out5), full_page=True)
            print("wrote", out5)

            # 06 - image upload: call /api/v1/vision/triage directly
            triage_url = BASE + '/api/v1/vision/triage'
            try:
                files = {'image': ('test.jpg', b'\xff\xd8\xff' + b'JFIF' + b'0' * 200, 'image/jpeg')}
                r = requests.post(triage_url, files=files, timeout=6)
                outj = OUT_DIR / '06_vision_triage.json'
                outj.write_text(json.dumps({'status_code': r.status_code, 'json': r.json() if r.status_code == 200 else r.text}, ensure_ascii=False), encoding='utf-8')
                print('vision triage saved', outj)
            except Exception as e:
                print('vision triage request failed', e)

            out6 = OUT_DIR / "06_image_upload.png"
            page.screenshot(path=str(out6), full_page=True)
            print("wrote", out6)

            # Save console / page errors
            save_console(OUT_DIR / 'playwright_console.log')

            browser.close()
    except Exception as e:
        print('Playwright capture script failed:', e)


if __name__ == '__main__':
    main()
