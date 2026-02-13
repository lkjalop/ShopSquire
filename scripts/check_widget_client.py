from playwright.sync_api import sync_playwright

URL = 'http://127.0.0.1:8081/ui/storefront'

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    messages = []
    def on_console(msg):
        messages.append(f"CONSOLE {msg.type}: {msg.text}")
    page_errors = []
    def on_page_error(err):
        page_errors.append(str(err))
    page.on('pageerror', on_page_error)
    page.on('console', on_console)
    resp = page.goto(URL, timeout=15000)
    print('status', resp.status)
    # evaluate presence
    el_exists = page.evaluate("() => !!document.querySelector('shopsquire-widget')")
    print('el_exists', el_exists)
    defined = page.evaluate("() => !!customElements.get('shopsquire-widget')")
    print('custom_defined', defined)
    has_shadow = page.evaluate("() => !!(document.querySelector('shopsquire-widget') && document.querySelector('shopsquire-widget').shadowRoot)")
    print('has_shadow', has_shadow)
    # attempt to click fab if available
    try:
        page.wait_for_selector('shopsquire-widget', timeout=3000)
        ok = page.evaluate("() => { const el=document.querySelector('shopsquire-widget'); if(!el) return 'noel'; const sr = el.shadowRoot; if(!sr) return 'noshadow'; const fab = sr.getElementById('fab'); if(!fab) return 'nofab'; fab.click(); return 'clicked'; }")
        print('click_result', ok)
    except Exception as e:
        print('wait_err', e)
    # Save a screenshot for visual inspection
    try:
        out = 'runs/storefront_widget.png'
        page.screenshot(path=out, full_page=True)
        print('screenshot_saved', out)
    except Exception as e:
        print('screenshot_err', e)
    # print a few console lines
    for m in messages[:50]:
        print(m)
    if page_errors:
        print('PAGE_ERRORS:')
        for e in page_errors:
            print(e)
    browser.close()
