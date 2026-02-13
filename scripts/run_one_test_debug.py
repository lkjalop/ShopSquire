from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
os.environ["PYTHONPATH"] = str(ROOT)
os.environ["DISABLE_UI_ROUTES"] = os.environ.get("DISABLE_UI_ROUTES", "0")
os.environ["SECURITY_OBSERVER_SYNC"] = "1"
os.environ["SECURITY_OBSERVER_SAMPLE_RATE"] = "1"
os.environ["SECURITY_OBSERVER_DEBUG"] = "1"

cmd = [sys.executable, "-m", "pytest", "-q", "-s", "tests/test_security_incident_flow.py::test_security_escalate_and_block_flow", "-vv"]
print("Running:", " ".join(cmd))
rc = subprocess.run(cmd).returncode
sys.exit(rc)
