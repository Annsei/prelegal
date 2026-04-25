# Stop and remove the Prelegal container on Windows.
$ErrorActionPreference = "Stop"

$Container = "prelegal"

$existing = docker ps -a --format "{{.Names}}" | Select-String -Pattern "^$Container$"
if ($existing) {
    Write-Host "[prelegal] Stopping $Container"
    docker rm -f $Container | Out-Null
} else {
    Write-Host "[prelegal] No container named $Container is running."
}
