import subprocess
import sys
from pathlib import Path

script = Path(__file__).parent / "run_tests_noninteractive.py"
if not script.exists():
    print(f"ERROR: target script not found: {script}", file=sys.stderr)
    sys.exit(2)

proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
out, err = proc.communicate()
print("=== STDOUT ===")
print(out)
print("=== STDERR ===")
print(err, file=sys.stderr)
print(f"=== EXIT CODE ===\n{proc.returncode}")
sys.exit(proc.returncode)
