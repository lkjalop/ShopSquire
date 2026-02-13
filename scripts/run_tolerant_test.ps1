Push-Location "D:/AI/agentLumen/ShopSquire"
$env:TEST_TOLERANT_GET_ERRORS = '1'
& ".venv/Scripts/python.exe" -m pytest tests/chaos/test_fault_injection.py::test_randomized_endpoint_mix_under_faults -q -s *>&1 | Tee-Object "runs/phase2_fault_capture_tolerant.txt"
Pop-Location
