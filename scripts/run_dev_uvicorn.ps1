Set-Location 'C:/AI/ShopSquire'
$env:DATABASE_URL = 'sqlite+pysqlite:///C:/AI/ShopSquire/tmp/e2e.sqlite'
New-Item -ItemType Directory -Force -Path 'C:/AI/ShopSquire/tmp' | Out-Null
$env:DISABLE_UI_ROUTES = '0'
$env:API_PORT = '8081'
$env:BACKPRESSURE_TEST_DELAY_SEC = '0.3'
$env:TEST_USE_DEMO_DECISION_TRACE = '1'
& '.venv/Scripts/python.exe' -m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8081 --factory
