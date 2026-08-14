from datetime import datetime, timezone

from src.app.services.behavioral_signal_projection import project_behavioral_signals


NOW = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)


def test_open_cart_is_right_censored_not_abandoned():
    view = project_behavioral_signals([{
        "session_id": "open", "event_type": "add_to_cart",
        "occurred_at": "2026-08-14T11:30:00Z", "consent_state": "granted",
    }], now=NOW)
    metric = next(row for row in view.measurements if row.metric == "cart_abandonment_rate")
    assert metric.state == "right_censored" and metric.value is None
    assert view.right_censored_sessions == 1


def test_mature_and_explicit_outcomes_produce_a_bounded_rate():
    events = [
        {"session_id": "old", "event_type": "add_to_cart", "occurred_at": "2026-08-12T00:00:00Z"},
        {"session_id": "buy", "event_type": "add_to_cart", "occurred_at": "2026-08-14T10:00:00Z"},
        {"session_id": "buy", "event_type": "purchase", "occurred_at": "2026-08-14T10:10:00Z"},
    ]
    metric = next(row for row in project_behavioral_signals(events, now=NOW).measurements
                  if row.metric == "cart_abandonment_rate")
    assert metric.value == 0.5 and metric.numerator == 1 and metric.denominator == 2


def test_hover_and_denied_consent_do_not_become_hidden_preferences():
    view = project_behavioral_signals([
        {"session_id": "a", "event_type": "hover", "occurred_at": "2026-08-14T10:00:00Z"},
        {"session_id": "a", "event_type": "click", "occurred_at": "2026-08-14T10:01:00Z"},
        {"session_id": "private", "event_type": "hover", "consent_state": "denied"},
    ], now=NOW)
    hover = next(row for row in view.measurements if row.metric == "hover_to_click_rate")
    assert hover.value == 1.0 and hover.denominator == 1
    assert view.withheld_sessions == 1 and view.ranking_authority == "none"
