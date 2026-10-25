from datetime import date

from src.app.services.fulfillment.sandbox_supplier import generate_reply


def test_supplier_quote_preserves_cents():
    reply = generate_reply(case_ref='fixture', scenario='full_quote', requested_qty=30,
                           unit_amount_cents=111599)
    assert '$1115.99 each' in reply['body']


def test_supplier_dates_follow_explicit_simulation_clock():
    args = dict(case_ref='fixture', requested_qty=40, as_of=date(2026, 9, 27))
    reply = generate_reply(scenario='full_quote', **args)
    assert '2026-10-02' in reply['body']
    assert '2026-10-07' in reply['body']
    assert 'valid until 2026-10-14' in reply['body']
    expired = generate_reply(scenario='expired_quote', **args)
    assert 'valid until 2026-09-19' in expired['body']


def test_default_clock_preserves_historical_replay():
    reply = generate_reply(case_ref='fixture', scenario='full_quote', requested_qty=30)
    assert '2026-07-03' in reply['body']
    assert '2026-07-15' in reply['body']
