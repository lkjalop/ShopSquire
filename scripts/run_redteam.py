import sys
import os
import json

# Ensure workspace root is on sys.path for imports when running as a script
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.app.security.redteam.suite import run_suite, REDTEAM_CASES


if __name__ == '__main__':
    try:
        results = run_suite(REDTEAM_CASES)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as exc:
        import traceback

        print('ERROR_RUNNING_REDTEAM_SUITE')
        traceback.print_exc()
        raise
