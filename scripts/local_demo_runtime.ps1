# Shared process configuration. Server variables apply only when Ollama is launched with them.
$demoRoot = Split-Path -Parent $PSScriptRoot
$demoProfile = Get-Content (Join-Path $demoRoot 'config/local_demo_runtime.json') -Raw | ConvertFrom-Json
if ($demoProfile.max_loaded_models -ne 1 -or $demoProfile.num_parallel -ne 1 -or
    $demoProfile.context_length -lt 1 -or $demoProfile.context_length -gt 4096) {
    throw 'Demo runtime exceeds the reviewed one-model, one-request, 4096-token bounds.'
}
$env:OLLAMA_HOST = '127.0.0.1:' + [string]$demoProfile.ollama_port
$env:OLLAMA_URL = 'http://' + $env:OLLAMA_HOST
# Match the exact configured port; do not allow all loopback destinations.
$env:INTERNAL_SERVICE_ALLOWLIST = $env:OLLAMA_HOST + ',localhost:' + [string]$demoProfile.ollama_port
$env:SSRF_ALLOW_PRIVATE = '0'
foreach ($name in @('ROUTER_MODEL','CLASSIFIER_MODEL','OLLAMA_DEFAULT_MODEL','OLLAMA_SMALL_MODEL',
    'OLLAMA_SUMMARY_MODEL','MULTI_INTENT_LLM_MODEL','LLM_PLANNER_MODEL','OPEN_WORLD_QUERY_MODEL',
    'PORTFOLIO_NARRATION_MODEL')) {
    [Environment]::SetEnvironmentVariable($name, $demoProfile.text_model, 'Process')
}
$env:OLLAMA_VISION_MODEL = $demoProfile.vision_model
$env:CV_VISION_MODEL = $demoProfile.vision_model
$env:CV_MODEL = $demoProfile.vision_model
$env:CV_PROVIDER = 'ollama'
$env:CV_VISION_TOTAL_TIMEOUT_SEC = [string]$demoProfile.vision_timeout_seconds
$env:CV_PROVIDER_TOTAL_TIMEOUT_S = [string]($demoProfile.vision_timeout_seconds + 5)
$env:CV_VISION_MAX_OUTPUT_TOKENS = [string]$demoProfile.vision_max_output_tokens
$env:OLLAMA_CONTEXT_LENGTH = [string]$demoProfile.context_length
$env:OLLAMA_MAX_LOADED_MODELS = [string]$demoProfile.max_loaded_models
$env:OLLAMA_NUM_PARALLEL = [string]$demoProfile.num_parallel
$env:LOCAL_MODEL_MAX_CONCURRENCY = '1'
$env:OLLAMA_KEEP_ALIVE = '2m'
$env:RESEARCH_POLICY_PROFILE = $demoProfile.research_profile
$env:EXTERNAL_RESEARCH_SEARCH_URL = $demoProfile.search_url
$env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = '1' # literal loopback only
$env:EXTERNAL_RESEARCH_ENABLED = '1'
$env:EXTERNAL_RESEARCH_TENANT_ALLOWLIST = $demoProfile.research_tenants -join ','
$env:EXTERNAL_RESEARCH_AUTO_AUTHORIZED = '0'
$env:APP_ENV = 'local'
$env:DATABASE_URL = 'sqlite:///' + ((Join-Path $demoRoot $demoProfile.database) -replace '\\','/')
$env:DATABASE_URL_RO = $env:DATABASE_URL
