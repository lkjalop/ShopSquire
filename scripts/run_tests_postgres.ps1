param([string]$ArtifactDirectory = (Join-Path $env:TEMP ('shopsquire-pg-cert-' + [guid]::NewGuid().ToString('N'))))

# Narrow PostgreSQL boundary certificate. The ordinary conftest selects SQLite.
$ErrorActionPreference = 'Stop'
$container = 'shopsquire-cert-' + [guid]::NewGuid().ToString('N')
$database = 'shopsquire_cert_' + [guid]::NewGuid().ToString('N')
$saved = @{}
foreach ($key in @('DATABASE_URL','DATABASE_URL_RO','RUN_POSTGRES_CERTIFICATE')) {
    $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$started = $false
$exitCode = 1
New-Item -ItemType Directory -Path $ArtifactDirectory -Force | Out-Null
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    docker run -d --name $container -p '127.0.0.1::5432' -e POSTGRES_USER=shopsquire -e "POSTGRES_DB=$database" -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Certificate container failed to start' }
    $started = $true
    $ready = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        docker exec $container pg_isready -U shopsquire -d $database 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready=$true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'PostgreSQL readiness failed' }
    $binding = (docker port $container 5432/tcp).Trim()
    if ($binding -notmatch '^127\.0\.0\.1:(\d+)$') { throw 'Unexpected certificate binding' }
    $env:DATABASE_URL = "postgresql+psycopg2://shopsquire@127.0.0.1:$($Matches[1])/$database"
    $env:DATABASE_URL_RO = $env:DATABASE_URL
    $env:RUN_POSTGRES_CERTIFICATE = '1'
    python -m alembic upgrade head *> (Join-Path $ArtifactDirectory 'migration.log')
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL migration failed; see migration.log' }
    python -m pytest --confcutdir=tests/certification tests/certification/test_postgres_draft_boundary.py -q "--junitxml=$ArtifactDirectory/results.xml" *> (Join-Path $ArtifactDirectory 'tests.log')
    $exitCode = $LASTEXITCODE
    [xml]$receipt = Get-Content (Join-Path $ArtifactDirectory 'results.xml')
    if ([int]$receipt.testsuites.testsuite.tests -lt 1 -or [int]$receipt.testsuites.testsuite.skipped -gt 0) {
        throw 'PostgreSQL certificate did not execute every required test'
    }
} finally {
    foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
    if ($started) {
        docker stop $container | Out-Null
        # Only this invocation's uniquely named disposable certificate DB.
        docker rm $container | Out-Null
    }
    Pop-Location
    Write-Host "Receipts: $ArtifactDirectory. Disposable certificate DB removed; application databases unchanged."
}
exit $exitCode
