"""An open CV circuit still records its health and containment evidence."""
def test_open_cv_circuit_records_metrics_and_trace_without_loading_a_provider(monkeypatch):
    from src.app.services import parallel_agent_executor as executor
    from src.app.services import decision_log

    metrics = []
    traces = []
    incidents = []
    monkeypatch.setattr(executor, 'evaluate_tool_intent', lambda **kwargs: {'allow': True})
    monkeypatch.setitem(executor._CB_STATE, 'cv_open_until', float('inf'))
    monkeypatch.setattr(executor, 'record_cb_state', lambda *args: metrics.append(args))
    monkeypatch.setattr(executor, 'record_incident_alert', lambda *args: incidents.append(args))
    monkeypatch.setattr(decision_log, 'log_trace_event', lambda **kwargs: traces.append(kwargs))

    assert executor._run_cv({'trace_id': 'owned-circuit-fixture'}) == {}
    assert metrics == [('cv_provider', True)]
    assert incidents == [('cv_circuit_breaker', 'medium')]
    assert len(traces) == 1
    assert traces[0]['event_type'] == 'circuit_breaker_open'
    assert traces[0]['trace_id'] == 'owned-circuit-fixture'
