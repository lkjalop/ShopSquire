# Apply Alembic migrations to the configured database.
# Usage:
#   $env:DATABASE_URL='postgresql://user:pw@host:5432/db'; .\scripts\apply_migrations.ps1
# or pass params: -DatabaseUrl
param(
    [string]$DatabaseUrl = $env:DATABASE_URL
)

if (-not $DatabaseUrl) {
    Write-Host "DATABASE_URL required (e.g. postgresql://user:pw@host:5432/db or sqlite+pysqlite:///path.sqlite)" -ForegroundColor Yellow
    exit 2
}

$env:DATABASE_URL = $DatabaseUrl

function Resolve-Alembic {
    $local = Join-Path (Get-Location) ".venv\Scripts\alembic.exe"
    if (Test-Path $local) { return $local }
    $poetry = Get-Command poetry -ErrorAction SilentlyContinue
    if ($poetry) { return "poetry" }
    return $null
}

$alembicCmd = Resolve-Alembic
if (-not $alembicCmd) {
    Write-Host "Alembic not found. Install deps (Poetry) or create a venv with alembic." -ForegroundColor Red
    exit 3
}

Write-Host "Applying Alembic migrations (DATABASE_URL=$DatabaseUrl)" -ForegroundColor Cyan
if ($alembicCmd -eq "poetry") {
    poetry run alembic -c alembic.ini upgrade head
    exit $LASTEXITCODE
}
& $alembicCmd -c alembic.ini upgrade head
exit $LASTEXITCODE
