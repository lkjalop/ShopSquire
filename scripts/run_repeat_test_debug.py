#!/usr/bin/env python3
import subprocess, sys, time

cmd = [sys.executable, 'scripts/run_one_test_debug.py']
max_runs = 20
for i in range(1, max_runs+1):
    print('=== RUN', i)
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print('Run', i, 'failed with exit code', rc)
        sys.exit(rc)
    time.sleep(0.2)
print('All runs succeeded')
sys.exit(0)
