import os
import sys
import pytest

# Simple runner to set environment variables and run pytest
if __name__ == '__main__':
    # Usage: python scripts/run_tests_target.py <db_url> <disable_tracing> [pytest args...]
    if len(sys.argv) < 3:
        print('Usage: run_tests_target.py <DATABASE_URL> <DISABLE_TRACING> [pytest args...]')
        sys.exit(2)
    os.environ['DATABASE_URL'] = sys.argv[1]
    os.environ['DISABLE_TRACING'] = sys.argv[2]
    args = sys.argv[3:] if len(sys.argv) > 3 else []
    rc = pytest.main(args)
    sys.exit(rc)
