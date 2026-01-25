import json
from tests.pw.helpers import wait_for_widget_open, wait_for_results, wait_for_comparison


def test_right_side_panel_grid_and_comparison(page, test_server):
    base = test_server["base_url"]
    page.goto(base + "/ui/storefront")
    page.wait_for_selector("shopsquire-widget")
    # open widget
    page.evaluate("document.querySelector('shopsquire-widget').shadowRoot.querySelector('#fab').click()")
    wait_for_widget_open(page)
    # send a query
    page.evaluate("const el = document.querySelector('shopsquire-widget'); el.shadowRoot.querySelector('#query').value = 'top 12 laptops'; el.shadowRoot.querySelector('#send').click();")
    # wait for results to render
    wait_for_results(page)

    # Force many results to exercise scrolling / 3x4 grid
    page.evaluate("(() => { const el = document.querySelector('shopsquire-widget'); el.state.results = Array.from({length:12}, (_,i)=>({id:'p'+i, name:'Test '+i, price:1000+i, rating:4.0, ram:16, storage:'512GB', reasons:['Reason']})); el.render(); })()")
    # ensure 12 cards exist
    page.wait_for_function("() => document.querySelector('shopsquire-widget').shadowRoot.querySelectorAll('[data-add]').length === 12", timeout=3000)
    cnt = page.evaluate("() => document.querySelector('shopsquire-widget').shadowRoot.querySelectorAll('[data-add]').length")
    assert cnt == 12

    # Click compare on first item and check comparison grid
    page.evaluate("() => { const el = document.querySelector('shopsquire-widget'); const first = el.shadowRoot.querySelector('[data-compare]'); if (first) first.click(); }")
    wait_for_comparison(page)
    cmp_html = page.evaluate("() => document.querySelector('shopsquire-widget').shadowRoot.querySelector('#comparison').innerHTML")
    assert cmp_html is not None and 'Comparison' in cmp_html

    # At minimum, verify we rendered 12 result cards and comparison
    assert cnt == 12
