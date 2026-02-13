# Claude CLI wrapper — calls the Anthropic Python SDK
# Usage: ./claude.ps1 "Your question or prompt here"
# Or: claude "Your question" (after alias setup)

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$venvPath = ".venv\Scripts\python.exe"
$scriptPath = "scripts/claude_cli.py"

if (-not (Test-Path $venvPath)) {
    Write-Error "Virtual environment not found at $venvPath. Please run setup first."
    exit 1
}

if (-not (Test-Path $scriptPath)) {
    Write-Error "Claude CLI script not found at $scriptPath. Creating it now..."
    exit 1
}

$prompt = $Args -join " "
& $venvPath $scriptPath $prompt
