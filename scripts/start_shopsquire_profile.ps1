param(
    [ValidateSet("fixture", "demo-live", "production")]
    [string]$Profile = "fixture",
    [string]$ArtifactRoot = "",
    [switch]$KeepServices,
    [string[]]$PlaywrightSpec = @()
)

$ErrorActionPreference = "Stop"
$scripts = $PSScriptRoot

switch ($Profile) {
    "fixture" {
        $args = @{}
        if ($ArtifactRoot) { $args.LogRoot = $ArtifactRoot }
        & (Join-Path $scripts "start_recording_stack.ps1") @args
    }
    "demo-live" {
        $args = @{ LiveDemo = $true }
        if ($ArtifactRoot) { $args.LogRoot = $ArtifactRoot }
        & (Join-Path $scripts "start_recording_stack.ps1") @args
    }
    "production" {
        # This is a production-shaped certification launcher, not a shortcut
        # around deployment controls. It provisions isolated PostgreSQL/Redis,
        # checks migration 20260874, and runs the selected no-retry browser gate.
        $args = @{ KeepServices = [bool]$KeepServices }
        if ($ArtifactRoot) { $args.ArtifactRoot = $ArtifactRoot }
        if ($PlaywrightSpec.Count -gt 0) { $args.PlaywrightSpec = $PlaywrightSpec }
        & (Join-Path $scripts "run_production_shaped_browser_battery.ps1") @args
    }
}
