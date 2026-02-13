import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "runs" / "repro_fault_injection"
LOG_DIR.mkdir(parents=True, exist_ok=True)

TEST = "tests/chaos/test_fault_injection.py::test_randomized_endpoint_mix_under_faults"
PY = sys.executable

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 100
for i in range(1, runs + 1):
    print(f"Run {i}")
    proc = subprocess.run([PY, "-m", "pytest", TEST, "-q", "-s", "-vv"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", errors="replace")
    fname = LOG_DIR / f"run_{i:03}.log"
    fname.write_text(out, encoding="utf-8")
    # Look for HTTP 500 in output
    if "500 Internal Server Error" in out or "status_code == 500" in out or "500 == 200" in out or "Internal Server Error" in out:
        print(f"Found 500 on run {i}, saved log to {fname}")
        print(out)
        sys.exit(0)
    # If pytest returned non-zero, still show summary for inspection but continue
    if proc.returncode != 0:
        print(f"Run {i} returned non-zero exit code {proc.returncode}; log saved to {fname}")

print("Completed all runs without detecting 500 in captured output.")
sys.exit(0)
