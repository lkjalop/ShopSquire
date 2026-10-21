"""Server opt-in for controls that are valid only in isolated test processes."""
import os


def isolated_test_controls_enabled() -> bool:
    return (str(os.getenv('APP_ENV', '')).strip().lower() == 'test'
            and str(os.getenv('ALLOW_TEST_REQUEST_BYPASS', '0')).strip() == '1')
