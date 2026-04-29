# Build and start the Prelegal container on Windows.
# Users + saved drafts persist across runs via a host-mounted volume.
$ErrorActionPreference = "Stop"

$Image     = "prelegal:latest"
$Container = "prelegal"
$Port      = 8000
$DataDir   = Join-Path $env:USERPROFILE ".prelegal\data"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

# The SQLite file lives in $DataDir on the host so registered users
# survive `docker rm`. Created if missing.
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

Write-Host "[prelegal] Building image: $Image"
docker build -t $Image .

# `docker rm -f` against a missing container is non-fatal; suppress its stderr.
docker rm -f $Container 2>$null | Out-Null

# Forward OPENROUTER_API_KEY (used by the AI chat) into the container.
# Prefer the project's .env file via --env-file, fall back to whatever is in
# the current shell. Missing key is OK -- the chat endpoint will return 502
# with a clear message until one is configured.
$envFile = Join-Path $Root ".env"
$envFlags = @()
if (Test-Path $envFile) {
    $envFlags = @("--env-file", $envFile)
} elseif ($env:OPENROUTER_API_KEY) {
    $envFlags = @("-e", "OPENROUTER_API_KEY=$($env:OPENROUTER_API_KEY)")
}

Write-Host "[prelegal] Starting container on http://localhost:$Port (data: $DataDir)"
docker run -d --name $Container `
    -p "${Port}:8000" `
    -v "${DataDir}:/data" `
    @envFlags $Image | Out-Null

Write-Host "[prelegal] Up. Tail logs with: docker logs -f $Container"
