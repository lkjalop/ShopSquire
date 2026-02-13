Push-Location "D:/AI/agentLumen/ShopSquire"
$env:TEST_TOLERANT_GET_ERRORS = '1'
& ".venv/Scripts/python.exe" -m pytest tests/chaos -q -vv *>&1 | Tee-Object "runs/phase2_full_after_tolerant.txt"
Pop-Location
