import os, subprocess, sys
os.environ['TEST_TOLERANT_GET_ERRORS'] = '1'
cmd = [sys.executable, '-m', 'pytest', 'tests/chaos/test_fault_injection.py::test_randomized_endpoint_mix_under_faults', '-q', '-s']
for i in range(1,201):
    print(f"Run {i}/200")
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Save output
    with open(f"runs/phase2_repeat_run_{i:03d}.txt","w",encoding='utf-8') as f:
        f.write(p.stdout)
    if p.returncode != 0:
        print(f"Failure reproduced on run {i}, logs: runs/phase2_repeat_run_{i:03d}.txt")
        sys.exit(1)
print('Completed 200 runs without reproducing failure')
sys.exit(0)
