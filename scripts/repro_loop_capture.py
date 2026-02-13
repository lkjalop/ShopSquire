import subprocess
import sys
import os

os.makedirs('runs', exist_ok=True)
py = sys.executable
test = 'tests/chaos/test_fault_injection.py::test_randomized_endpoint_mix_under_faults'
cmd = [py, '-m', 'pytest', test, '-q', '-s']

import os

try:
    MAX_RUNS = int(os.getenv("REPRO_MAX_RUNS", "1000"))
except Exception:
    MAX_RUNS = 1000
for i in range(1, MAX_RUNS + 1):
    print(f'Run {i}/{MAX_RUNS}')
    fname = f'runs/phase2_repeat_run_{i:04d}.txt'
    with open(fname, 'w', encoding='utf-8', buffering=1) as out_f:
        # start process and stream stdout/stderr to file to avoid large-buffer hangs
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for line in p.stdout:
                out_f.write(line)
        except Exception:
            p.kill()
            p.wait()
        ret = p.wait()
    if ret != 0:
        print(f'Failure reproduced on run {i}, logs: {fname}')
        sys.exit(1)

print(f'Completed {MAX_RUNS} runs without reproducing failure')
sys.exit(0)
