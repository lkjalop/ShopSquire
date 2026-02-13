import os
import subprocess
import sys

os.environ['SECURITY_OBSERVER_DEBUG'] = '1'
os.environ['LOG_LEVEL'] = 'DEBUG'

cmd = [sys.executable, '-m', 'pytest', 'tests/chaos/test_fault_injection.py::test_randomized_endpoint_mix_under_faults', '-q', '-s']
print('Running:', ' '.join(cmd))
with open('runs/phase2_fault_capture.txt', 'w', encoding='utf-8') as f:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        f.write(line)
        print(line, end='')
    p.wait()
    sys.exit(p.returncode)
