param(
    [switch]$IncludeUi,
    [switch]$IncludeMigrationRehearsal
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startedAt = Get-Date
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-ProofStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    $stepStarted = Get-Date
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "$Name exited with code $LASTEXITCODE"
        }
        $results.Add([ordered]@{
            name = $Name
            status = "passed"
            duration_seconds = [math]::Round(((Get-Date) - $stepStarted).TotalSeconds, 2)
        })
    }
    catch {
        $results.Add([ordered]@{
            name = $Name
            status = "failed"
            duration_seconds = [math]::Round(((Get-Date) - $stepStarted).TotalSeconds, 2)
            error = $_.Exception.Message
        })
        throw
    }
}

Push-Location $repoRoot
try {
    $commit = (git rev-parse HEAD).Trim()
    Invoke-ProofStep "Governed AI/ML and procurement contracts" {
        pytest -q `
            tests/services/test_inventory_projection_read_model.py `
            tests/services/test_inventory_event_projection.py `
            tests/services/test_forecast_interval_calibration.py `
            tests/services/test_synthetic_causal_evaluation.py `
            tests/services/test_supply_market_intelligence.py `
            tests/services/test_supply_risk_workbench.py `
            tests/services/test_supply_hypothesis_workflow.py `
            tests/services/test_public_market_source_fetch.py `
            tests/services/test_account_timeline.py `
            tests/services/test_party_redirect_execution.py `
            tests/services/fulfillment/test_supplier_catalog_transaction_isolation.py
    }

    Invoke-ProofStep "Changed implementation Ruff gate" {
        ruff check `
            src/app/services/inventory_projection_read_model.py `
            src/app/services/inventory_event_projection.py `
            src/app/services/synthetic_causal_evaluation.py `
            src/app/services/supply_graph_repository.py `
            src/app/services/market_evidence_policy.py
    }

    if ($IncludeUi) {
        Invoke-ProofStep "Admin component suite" {
            Push-Location (Join-Path $repoRoot "src/frontend/admin-react")
            try {
                npm test -- --run
            }
            finally {
                Pop-Location
            }
        }
        Invoke-ProofStep "Admin production build" {
            Push-Location (Join-Path $repoRoot "src/frontend/admin-react")
            try {
                npm run build
            }
            finally {
                Pop-Location
            }
        }
    }

    if ($IncludeMigrationRehearsal) {
        Invoke-ProofStep "Empty-database migration upgrade/rollback/re-upgrade" {
            $proofDir = Join-Path $repoRoot ".tmp-portfolio-proof"
            New-Item -ItemType Directory -Force -Path $proofDir | Out-Null
            $databasePath = Join-Path $proofDir ("migration-" + [guid]::NewGuid().ToString("N") + ".sqlite")
            $env:DATABASE_URL = "sqlite+pysqlite:///" + ($databasePath -replace "\\", "/")
            $env:DATABASE_URL_RO = $env:DATABASE_URL
            alembic upgrade head
            alembic downgrade -1
            alembic upgrade head
            alembic current
        }
    }

    $finishedAt = Get-Date
    $report = [ordered]@{
        generated_at = $finishedAt.ToUniversalTime().ToString("o")
        commit = $commit
        authority = "test_evidence_only"
        production_certification = $false
        elapsed_seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 2)
        results = $results
        claims = [ordered]@{
            deterministic_inventory_replay = "tested"
            forecast_interval_evidence = "tested"
            synthetic_policy_evaluation = "simulation_only"
            public_market_intelligence = "advisory_only"
            public_source_families = "cpsc_world_bank_usgs"
            party_identity_execution = "reversible_redirect_only"
            autonomous_procurement = "not_claimed"
        }
    }
    $runsDir = Join-Path $repoRoot "runs"
    New-Item -ItemType Directory -Force -Path $runsDir | Out-Null
    $reportPath = Join-Path $runsDir "ai_ml_portfolio_proof.json"
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host ""
    Write-Host "Proof report: $reportPath" -ForegroundColor Green
}
finally {
    Pop-Location
}
