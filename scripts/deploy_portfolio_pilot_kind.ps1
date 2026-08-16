param(
    [string]$Release = 'shopsquire-pilot',
    [string]$Namespace = 'shopsquire-pilot'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$chart = Join-Path $repoRoot 'helm/shopsquire'
$values = Join-Path $chart 'values-portfolio-pilot.yaml'

kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f - | Out-Null

# Phase one deliberately has no API replica. PostgreSQL/Redis start, and one
# migration Job becomes the only schema writer.
helm upgrade --install $Release $chart --namespace $Namespace `
  --values $values --set replicaCount=0 --set image.repository=shopsquire-api `
  --set image.tag=portfolio-pilot

$job = kubectl get jobs -n $Namespace -l app.kubernetes.io/component=migration `
  --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}'
if (-not $job) { throw 'Migration Job was not created.' }
kubectl wait --for=condition=complete --timeout=300s "job/$job" -n $Namespace

# Phase two removes the completed Job from desired state and starts the API.
helm upgrade $Release $chart --namespace $Namespace --values $values `
  --set migrationJob.enabled=false --set replicaCount=1 `
  --set image.repository=shopsquire-api --set image.tag=portfolio-pilot
kubectl rollout status "deployment/$Release" -n $Namespace --timeout=300s

Write-Output "Portfolio pilot deployed with persistent PostgreSQL/Redis and migration job $job."
Write-Output "Supplier mode remains sandbox; real RFQ sending is disabled."
