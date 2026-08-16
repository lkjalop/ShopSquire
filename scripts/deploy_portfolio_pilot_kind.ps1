param(
    [string]$Release = 'shopsquire-pilot',
    [string]$Namespace = 'shopsquire-pilot',
    [string]$ClusterName = 'shopsquire-local',
    [string]$ImageTag = 'portfolio-pilot',
    [switch]$BuildImage,
    [switch]$BootstrapPilotSecrets
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$chart = Join-Path $repoRoot 'helm/shopsquire'
$values = Join-Path $chart 'values-portfolio-pilot.yaml'
$image = "shopsquire-api:$ImageTag"

function Resolve-Tool([string]$Name, [string]$WingetPattern) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidate = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
      -Recurse -Filter "$Name.exe" -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -like "*$WingetPattern*" } |
      Select-Object -First 1 -ExpandProperty FullName
    if (-not $candidate) { throw "$Name is required. Install it with winget before deployment." }
    return $candidate
}

$helm = Resolve-Tool 'helm' 'Helm.Helm*'
$kind = Resolve-Tool 'kind' 'Kubernetes.kind*'

if ($BuildImage) {
    docker build --target api-runtime -f (Join-Path $repoRoot 'Dockerfile.runtime') `
      -t $image $repoRoot
    if ($LASTEXITCODE -ne 0) { throw 'API image build failed.' }
}
docker image inspect $image *> $null
if ($LASTEXITCODE -ne 0) { throw "Image $image is absent. Re-run with -BuildImage." }
& $kind load docker-image $image --name $ClusterName
if ($LASTEXITCODE -ne 0) { throw 'Loading the API image into Kind failed.' }

kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f - | Out-Null

if ($BootstrapPilotSecrets -and -not (kubectl get secret shopsquire-pilot-identities -n $Namespace `
  --ignore-not-found -o name)) {
    function New-PilotKey {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    }
    $secret = @{
        apiVersion = 'v1'; kind = 'Secret';
        metadata = @{ name = 'shopsquire-pilot-identities'; namespace = $Namespace };
        type = 'Opaque';
        stringData = @{
            MERCHANT_API_KEY = New-PilotKey
            OWNER_API_KEY = New-PilotKey
            DEVELOPER_API_KEY = New-PilotKey
        }
    } | ConvertTo-Json -Depth 6 -Compress
    $secret | kubectl apply -f - | Out-Null
}
if (-not (kubectl get secret shopsquire-pilot-identities -n $Namespace `
  --ignore-not-found -o name)) {
    throw 'Pilot identity Secret is absent. Supply it or use -BootstrapPilotSecrets.'
}

# Phase one deliberately has no API replica. PostgreSQL/Redis start, and one
# migration Job becomes the only schema writer.
& $helm upgrade --install $Release $chart --namespace $Namespace `
  --values $values --set replicaCount=0 --set image.repository=shopsquire-api `
  --set "image.tag=$ImageTag"

$job = kubectl get jobs -n $Namespace -l app.kubernetes.io/component=migration `
  --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}'
if (-not $job) { throw 'Migration Job was not created.' }
kubectl wait --for=condition=complete --timeout=300s "job/$job" -n $Namespace

# Phase two removes the completed Job from desired state and starts the API.
& $helm upgrade $Release $chart --namespace $Namespace --values $values `
  --set migrationJob.enabled=false --set replicaCount=1 `
  --set image.repository=shopsquire-api --set "image.tag=$ImageTag"
kubectl rollout status "deployment/$Release" -n $Namespace --timeout=300s

kubectl exec -n $Namespace "deployment/$Release" -- env PYTHONPATH=/app `
  python scripts/enrol_portfolio_pilot.py
if ($LASTEXITCODE -ne 0) { throw 'Server-derived pilot identity enrollment failed.' }

Write-Output "Portfolio pilot deployed with persistent PostgreSQL/Redis and migration job $job."
Write-Output "Supplier mode remains sandbox; real RFQ sending is disabled."
