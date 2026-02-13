# Start Postgres test container, run pytest against it, then tear down
$compose = Join-Path $PSScriptRoot "..\docker-compose.postgres.yml"
Write-Host "Using docker-compose file: $compose"

# Start services in background
docker compose -f $compose up -d

# Wait for health
Write-Host "Waiting for Postgres to become healthy..."
$healthy = $false
for ($i=0; $i -lt 60; $i++) {
    $hc = docker inspect --format='{{json .State.Health.Status}}' $(docker compose -f $compose ps -q postgres-test) 2>$null
    if ($hc -and $hc -like '*"healthy"*') { $healthy = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $healthy) { Write-Error "Postgres did not become healthy in time"; docker compose -f $compose logs --no-color; exit 1 }

# Build DATABASE_URL
$env:DATABASE_URL = "postgresql+psycopg2://shopsquire:shopsquire@localhost:5433/shopsquire_test"
$env:PYTHONPATH = "."

# Run pytest
pytest -q | Tee-Object -FilePath runs\pytest_postgres_run.txt
$code = $LASTEXITCODE

# Tear down
docker compose -f $compose down

exit $code
