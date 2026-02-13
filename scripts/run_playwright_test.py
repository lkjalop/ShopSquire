import os
import sys
import pytest

# Ensure Playwright tests enabled and deterministic port
os.environ['DISABLE_PLAYWRIGHT_TESTS'] = '0'
os.environ['PLAYWRIGHT_TEST_PORT'] = os.environ.get('PLAYWRIGHT_TEST_PORT', '8099')
# Use a focused test by default, can be overridden by CLI args
tests = sys.argv[1:] or ['tests/pw/test_decision_trace_nlp_panels.py']
print(f"Running Playwright tests: {tests} on port {os.environ['PLAYWRIGHT_TEST_PORT']}")
rc = pytest.main(['-q', *tests, '-s'])
raise SystemExit(rc)
