<#
PowerShell script to:
1) Activate the project's virtualenv (.venv) using Activate.ps1
2) Install pytest, requests, pyyaml via pip
3) Run the requested pytest test and capture stdout/stderr and exit code

Outputs created in the current directory:
- pip_install_out.txt
- pytest_run_out.txt
- pytest_exit_code.txt
#>

$ErrorActionPreference = 'Stop'

$activatePath = Join-Path -Path $PWD -ChildPath ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $activatePath)) {
    Write-Error ".venv not found at $activatePath. Ensure you have created the virtualenv.";
    exit 2
}

Write-Host "Activating virtualenv: $activatePath"
& $activatePath

# Ensure Python can import the repository packages during pytest collection
$env:PYTHONPATH = (Get-Location).Path
Write-Host "Set PYTHONPATH to $env:PYTHONPATH"

# Ensure tests run against a local SQLite DB unless DATABASE_URL is explicitly set
if (-not $env:DATABASE_URL) {
    # ensure runs directory exists
    $runsDir = Join-Path -Path $PWD -ChildPath "runs"
    if (-not (Test-Path $runsDir)) { New-Item -ItemType Directory -Path $runsDir | Out-Null }
    $dbPath = (Join-Path -Path $runsDir -ChildPath "test_db.sqlite").ToString().Replace('\\','/')
    $env:DATABASE_URL = "sqlite+pysqlite:///$dbPath"
    Write-Host "Set DATABASE_URL to $env:DATABASE_URL"
}

Write-Host "Installing packages: pytest requests pyyaml"
pip install pytest requests pyyaml 2>&1 | Tee-Object -FilePath pip_install_out.txt

Write-Host "Applying DB schema for tests"
python scripts/apply_schema_for_tests.py
Write-Host "Creating minimal tables required by tests"
python scripts/create_minimal_test_schema.py

$testArgs = @('-m', 'pytest', '-q', 'tests/test_security_incident_flow.py::test_security_escalate_and_block_flow')
Write-Host "Running: python $testArgs"
"Running pytest via cmd to capture stdout+stderr into file"
$cmdline = "python -m pytest -q tests/test_security_incident_flow.py::test_security_escalate_and_block_flow 1> pytest_run_out.txt 2>&1"
Write-Host $cmdline
cmd /c $cmdline

$exit = $LASTEXITCODE
"$exit" | Out-File -FilePath pytest_exit_code.txt -Encoding utf8

Write-Host "Test run completed. Exit code: $exit"
Write-Host "Files written: pip_install_out.txt, pytest_run_out.txt, pytest_exit_code.txt"
