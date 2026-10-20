"""Release the synchronous browser loop before a later async test module.

Delegate launch options, connection settings, tracing and cleanup to the pinned
pytest-playwright fixtures. Only their ownership scope changes.
"""
import importlib.util

import pytest


if importlib.util.find_spec("pytest_playwright") is not None:
    from pytest_playwright import pytest_playwright as upstream

    playwright = pytest.fixture(scope="module")(upstream.playwright.__wrapped__)
    browser_type = pytest.fixture(scope="module")(upstream.browser_type.__wrapped__)
    launch_browser = pytest.fixture(scope="module")(upstream.launch_browser.__wrapped__)
    browser = pytest.fixture(scope="module")(upstream.browser.__wrapped__)
    browser_context_args = pytest.fixture(scope="module")(upstream.browser_context_args.__wrapped__)
