Push-Location 'D:/AI/agentLumen/ShopSquire'
$env:PYTHONPATH = (Get-Location).Path
& '.venv/Scripts/python.exe' scripts/tmp_test_log_decision.py
Pop-Location
