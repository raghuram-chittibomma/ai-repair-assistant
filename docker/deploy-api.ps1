# Deploy API on the LAN Docker host (LAN_HOST)
#
# Run this script **on the Docker host** (RDP / local shell), from the repo root.
# Postgres is already running on HOST_PORT (default 5436); this starts the API on
# API_PORT (default 8080).
#
# Prerequisites on the host:
#   - Docker
#   - Repo checkout with .env.local (OPENAI_API_KEY, POSTGRES_PASSWORD, etc.)

param(
    [string]$EnvFile = ".env.local"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing $EnvFile — copy .env.example and fill in values."
}

# Load POSTGRES_* and API_PORT for docker run
$envMap = @{}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $k, $v = $line.Split("=", 2)
    $envMap[$k.Trim()] = $v.Trim().Trim('"').Trim("'")
}

$user = $envMap["POSTGRES_USER"]
if (-not $user) { $user = "repair" }
$pass = $envMap["POSTGRES_PASSWORD"]
$db = $envMap["POSTGRES_DB"]
if (-not $db) { $db = "repair_assistant" }
$hostPort = $envMap["HOST_PORT"]
if (-not $hostPort) { $hostPort = "5436" }
$apiPort = $envMap["API_PORT"]
if (-not $apiPort) { $apiPort = "8080" }

if (-not $pass) { Write-Error "POSTGRES_PASSWORD must be set in $EnvFile" }

Write-Host "Building ai-repair-assistant-api..."
docker build -f docker/Dockerfile -t ai-repair-assistant-api .

Write-Host "Stopping old API container if present..."
docker rm -f ai-repair-assistant-api 2>$null | Out-Null

$dbUrl = "postgresql://${user}:${pass}@host.docker.internal:${hostPort}/${db}"

Write-Host "Starting API on port $apiPort (DB via host.docker.internal:$hostPort)..."
docker run -d `
    --name ai-repair-assistant-api `
    --restart unless-stopped `
    -p "${apiPort}:8080" `
    --add-host=host.docker.internal:host-gateway `
    --env-file $EnvFile `
    -e DATABASE_URL=$dbUrl `
    -e REPAIR_API_HOST=0.0.0.0 `
    -e REPAIR_API_PORT=8080 `
    ai-repair-assistant-api

Write-Host ""
Write-Host "Done. From the LAN:"
Write-Host "  http://<host-ip>:${apiPort}/ui"
Write-Host "  http://<host-ip>:${apiPort}/health"
Write-Host ""
docker ps --filter name=ai-repair-assistant-api --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
