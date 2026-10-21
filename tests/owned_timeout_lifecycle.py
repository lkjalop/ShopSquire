"""Release completed pytest-timeout callbacks after its cancellation succeeds."""
import pytest


@pytest.hookimpl(hookwrapper=True, tryfirst=True, optionalhook=True)
def pytest_timeout_cancel_timer(item):
    outcome = yield
    # The existing backend cancels and joins its timer. Keep a failed/active
    # cancellation observable; only release the successfully completed callback.
    if outcome.excinfo is None:
        item.__dict__.pop('cancel_timeout', None)
