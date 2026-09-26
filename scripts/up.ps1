# Build sandbox images + the stack, start it, wait for health.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose -f infra/docker-compose.yml --profile images build emulator-image emulator-floci-image emulator-ministack-image terminal-image
docker compose -f infra/docker-compose.yml up -d --build
Write-Host "waiting for http://localhost:3000/healthz ..."
for ($i = 0; $i -lt 90; $i++) {
  try { Invoke-WebRequest -UseBasicParsing http://localhost:3000/healthz | Out-Null; Write-Host "CloudLabs is up: http://localhost:3000"; exit 0 } catch { Start-Sleep 2 }
}
Write-Error "stack did not become healthy; see: docker compose -f infra/docker-compose.yml logs api runner"
