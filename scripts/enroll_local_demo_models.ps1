# The universal model gateway verifies the exact installed Ollama manifest. A
# portfolio launcher has no deployment secret store, so enrol the currently
# installed *local* artifacts explicitly at launch and fail closed if Ollama
# cannot attest them. Production profiles must supply reviewed digests instead.
function Get-LocalOllamaDigest([string]$ModelName) {
    try {
        $manifest = Invoke-RestMethod -Uri ($env:OLLAMA_URL + '/api/tags') -TimeoutSec 5
        $entry = @($manifest.models) | Where-Object {
            [string]$_.name -eq $ModelName -or [string]$_.model -eq $ModelName
        } | Select-Object -First 1
        $digest = [string]$entry.digest
        if ($digest -notmatch '^[a-fA-F0-9]{64}$') {
            throw "missing or invalid manifest digest"
        }
        return $digest.ToLowerInvariant()
    } catch {
        throw "Cannot enrol local Ollama artifact '$ModelName': $($_.Exception.Message)"
    }
}

$routerModelDigest = Get-LocalOllamaDigest $env:ROUTER_MODEL
$visionModelDigest = Get-LocalOllamaDigest $env:OLLAMA_VISION_MODEL
$env:OLLAMA_DEFAULT_MODEL_DIGEST = $routerModelDigest
$env:OLLAMA_SMALL_MODEL_DIGEST = $routerModelDigest
$env:OLLAMA_MEDIUM_MODEL_DIGEST = $routerModelDigest
$env:ROUTER_MODEL_DIGEST = $routerModelDigest
$env:CLASSIFIER_MODEL_DIGEST = $routerModelDigest
$env:RECOMMEND_INTENT_MODEL_DIGEST = $routerModelDigest
$env:MULTI_INTENT_LLM_MODEL_DIGEST = $routerModelDigest
$env:LLM_PLANNER_MODEL_DIGEST = $routerModelDigest
$env:CV_OCR_MODEL_DIGEST = $visionModelDigest
$env:CV_IDENTITY_MODEL_DIGEST = $visionModelDigest
$env:MODEL_ARTIFACT_ENROLLMENT_MODE = "local_demo_observed_manifest"
