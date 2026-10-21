from scripts.soak_portfolio_browser import run


def test_soak_requires_full_duration_and_multiple_successful_cycles():
    clock = [0.0]
    reports = []
    result = run(duration=120, interval=30, invoke=lambda index: 0,
                 fingerprint=lambda: 'same', report=reports.append,
                 monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    assert result['status'] == 'passed'
    assert result['elapsed_seconds'] >= 120
    assert result['successful_cycles'] == 4
    assert all(r['status'] != 'passed' for r in reports[:-1])


def test_failure_or_source_change_cannot_become_soak_success():
    for changed in (True, False):
        stamps = iter(['initial', 'changed' if changed else 'initial'])
        result = run(duration=120, interval=30, invoke=lambda index: 1,
                     fingerprint=lambda: next(stamps), report=lambda value: None,
                     monotonic=lambda: 0, sleep=lambda seconds: None)
        assert result['status'] == 'failed'
        assert result['successful_cycles'] == 0


def test_harness_exception_records_failure_instead_of_leaving_running_status():
    def broken(index):
        raise OSError('diagnostic collection failed')
    reports = []
    result = run(duration=120, interval=30, invoke=broken, fingerprint=lambda:'same',
                 report=reports.append, monotonic=lambda:0, sleep=lambda seconds:None)
    assert result['status'] == 'failed'
    assert result['reason'] == 'harness_exception'
    assert reports[-1]['error_type'] == 'OSError'


def test_sixty_minute_checkpoint_counts_the_completed_interval():
    clock=[0.0]
    result=run(duration=3600,interval=60,invoke=lambda _:0,fingerprint=lambda:'fixed',report=lambda _:None,
        monotonic=lambda:clock[0],sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    assert result['status']=='passed'
    assert result['sixty_minute_checkpoint'] is True


def test_resource_limits_fail_closed_and_identify_the_limit():
    from scripts.soak_portfolio_browser import resource_violation
    healthy={'memory_available_bytes':2*1024**3,'application_processes':[{'rss_bytes':1024**3,'handles':100}]}
    assert resource_violation(healthy) is None
    assert resource_violation({**healthy,'memory_available_bytes':100})=='host_available_memory'
    assert resource_violation({**healthy,'application_processes':[{'rss_bytes':3*1024**3,'handles':100}]})=='process_rss'
    assert resource_violation({**healthy,'application_processes':[{'rss_bytes':100,'handles':6000}]})=='process_handles'
