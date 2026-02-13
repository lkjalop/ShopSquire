import os
import subprocess
import sys

os.environ['SECURITY_OBSERVER_DEBUG'] = '1'
os.environ['LOG_LEVEL'] = 'DEBUG'

cmd = [sys.executable, '-m', 'pytest', 'tests/chaos/test_fault_injection.py::test_randomized_endpoint_mix_under_faults', '-q', '-s']
for i in range(1, 51):
    out_path = f"runs/phase2_fault_capture_run_{i:03d}.txt"
    print(f"Run {i}/50 -> {out_path}")
    with open(out_path, 'w', encoding='utf-8') as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        print(f"Failure reproduced on run {i}, captured to {out_path}")
        sys.exit(1)
print('Completed all runs without reproducing failure')
sys.exit(0)
