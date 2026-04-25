# Build and start the Prelegal container on Windows.
# DB is recreated from scratch on every run -- by design.
$ErrorActionPreference = "Stop"

$Image     = "prelegal:latest"
$Container = "prelegal"
$Port      = 8000

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

Write-Host "[prelegal] Building image: $Image"
docker build -t $Image .

# `docker rm -f` against a missing container is non-fatal; suppress its stderr.
docker rm -f $Container 2>$null | Out-Null

Write-Host "[prelegal] Starting container on http://localhost:$Port"
docker run -d --name $Container -p "${Port}:8000" $Image | Out-Null

Write-Host "[prelegal] Up. Tail logs with: docker logs -f $Container"
