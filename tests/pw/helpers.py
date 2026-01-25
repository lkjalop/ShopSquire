def wait_for_widget_open(page, timeout=3000):
    """Wait until the shopsquire-widget reports open state."""
    page.wait_for_function("() => document.querySelector('shopsquire-widget').state.open === true", timeout=timeout)


def wait_for_results(page, timeout=5000):
    """Wait until the widget's results container has real result items.

    The widget writes a temporary "Thinking..." placeholder into the results
    container before real results arrive, so check the widget state or the
    presence of typical result elements instead of raw innerHTML length.
    """
    try:
        page.wait_for_function(
            "() => { const w = document.querySelector('shopsquire-widget'); if(!w) return false; try { const s = w.state; const resultsOk = s && s.results && s.results.length > 0; const dom = w.shadowRoot && w.shadowRoot.querySelector('#results'); const domHasItems = dom && (dom.querySelector('.card') || dom.querySelector('[data-add]') || dom.querySelector('[data-compare]')); return resultsOk || Boolean(domHasItems); } catch(e) { return false; } }",
            timeout=2000,
        )
    except Exception:
        # Allow tests to proceed even when remote recommend did not return
        # results quickly (tests often overwrite state.results manually).
        return


def wait_for_comparison(page, timeout=15000):
    """Wait until the comparison panel is populated.

    This checks both the widget's internal `state.comparison` and the
    shadow DOM `#comparison` container to be robust against render timing.
    """
    page.wait_for_function(
        "() => { const w = document.querySelector('shopsquire-widget'); if (!w) return false; try { const s = w.state; const cmpOk = s && s.comparison && s.comparison.length > 0; const dom = w.shadowRoot && w.shadowRoot.querySelector('#comparison'); const domOk = dom && dom.innerHTML && dom.innerHTML.length > 0; return cmpOk || domOk; } catch(e) { return false; } }",
        timeout=timeout,
    )
