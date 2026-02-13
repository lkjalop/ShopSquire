import os
import sys
import pytest

if __name__ == '__main__':
    # Ensure repository package imports work during pytest collection
    os.environ['PYTHONPATH'] = os.getcwd()
    # Run the target test file passed as first arg, defaulting to the orchestrator test
    test_file = sys.argv[1] if len(sys.argv) > 1 else 'tests/services/test_orchestrator_tiering.py'
    sys.exit(pytest.main([test_file, '-q', '-s']))
