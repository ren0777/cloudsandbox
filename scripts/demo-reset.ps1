# One-command demo reset (PLAN §16). Requires the stack to be running (scripts/up.ps1).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose -f infra/docker-compose.yml exec -T api python -m app.demo reset
exit $LASTEXITCODE
