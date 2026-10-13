#!/usr/bin/env bash
# Laptop pilot: the PRODUCTION stack on this machine (docs/DEPLOYMENT.md §12). Run from Git Bash on Windows, or bash.
#
#   scripts/pilot.sh up --lan [ADDRESS]      classroom network: https://<laptop address>:8443 (self-signed certificate)
#   scripts/pilot.sh up                      public HTTPS through Cloudflare Tunnel (needs outbound port 7844)
#   scripts/pilot.sh admin EMAIL "NAME"      create an admin; prints a temporary password (changed at first sign-in)
#   scripts/pilot.sh url                     print the address students use
#   scripts/pilot.sh down                    stop everything (data is kept)
#
# The first `up` creates infra/laptop-pilot/state/production.env (secrets, git-ignored) and a self-signed certificate.
# Tunnel mode without CLOUDFLARE_TUNNEL_TOKEN in that file uses a QUICK tunnel: no account, a random
# https://….trycloudflare.com name that changes on every `up`. For a fixed name, set the token of a named tunnel and
# its hostname (PUBLIC_HOST) there.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
STATE=infra/laptop-pilot/state
ENV="$STATE/production.env"

secret() { openssl rand -hex 32; }
get() { grep "^$1=" "$ENV" | head -1 | cut -d= -f2-; }
set_var() {  # replace KEY=…, or add it (state files from older versions of this script)
  if grep -q "^$1=" "$ENV"; then sed -i "s#^$1=.*#$1=$2#" "$ENV"; else echo "$1=$2" >> "$ENV"; fi
}

compose() {
  local overlay=infra/laptop-pilot/docker-compose.tunnel.yml
  [ "$(get PILOT_MODE)" = "lan" ] && overlay=infra/laptop-pilot/docker-compose.lan.yml
  docker compose -p cloudlabs-pilot -f infra/docker-compose.yml -f infra/production/docker-compose.prod.yml \
    -f "$overlay" --env-file "$ENV" "$@"
}

init_state() {
  [ -f "$ENV" ] && return
  mkdir -p "$STATE/tls" "$STATE/acme"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=cloudlabs-pilot" \
    -keyout "$STATE/tls/privkey.pem" -out "$STATE/tls/fullchain.pem" 2>/dev/null
  cat > "$ENV" <<EOF
# Laptop pilot secrets (generated $(date +%F)). Keep this file private; it is git-ignored.
PILOT_MODE=tunnel
PUBLIC_HOST=pending
CL_SECRET_KEY=$(secret)
CL_RUNNER_SECRET=$(secret)
POSTGRES_SUPERUSER_PASSWORD=$(secret)
CLOUDLABS_OWNER_PASSWORD=$(secret)
CLOUDLABS_APP_PASSWORD=$(secret)
CL_DEFAULT_EMULATOR=floci
# seats: concurrent labs on this laptop (docs/LOADTEST.md measured 16 seats on a 6-vCPU Docker VM)
RUNNER_MAX_SANDBOXES=8
TLS_DIR=$(pwd)/$STATE/tls
ACME_DIR=$(pwd)/$STATE/acme
# Named tunnel (fixed address): set the token, and PUBLIC_HOST to its hostname.
CLOUDFLARE_TUNNEL_TOKEN=
TUNNEL_COMMAND=tunnel --protocol http2 --url https://gateway:443 --no-tls-verify
EOF
  chmod 600 "$ENV"
  echo "created $ENV (secrets) and a self-signed certificate"
}

lan_address() {
  # the adapter that is actually on the network has a default gateway (disconnected adapters show 169.254.x.x,
  # Docker's and WSL's virtual adapters have none)
  powershell.exe -NoProfile -Command "Get-NetIPConfiguration | Where-Object { \$_.IPv4DefaultGateway -and \$_.NetAdapter.Status -eq 'Up' } | ForEach-Object { \$_.IPv4Address.IPAddress } | Where-Object { \$_ -notlike '169.254.*' } | Select-Object -First 1" 2>/dev/null | tr -d '\r' || true
}

quick_url() {
  # `|| true`: no name yet is not an error (set -e would end the script); the caller keeps polling
  { compose logs tunnel 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1; } || true
}

wait_healthy() {
  for _ in $(seq 1 90); do
    if compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=3)" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "the API did not become healthy; see: docker compose -p cloudlabs-pilot logs api" >&2
  exit 1
}

import_labs() {
  # shellcheck disable=SC2046
  compose exec -T api python -m app.labs.importer $(ls labs | sed 's#^#/labs/#') | grep -v '^{' || true
}

up_lan() {
  local addr=${1:-$(lan_address)}
  [ -n "$addr" ] || { echo "could not find this laptop's network address; pass it: scripts/pilot.sh up --lan 192.168.1.20" >&2; exit 1; }
  set_var PILOT_MODE lan
  set_var PUBLIC_HOST "$addr:8443"   # the API only accepts WebSocket origins from PUBLIC_HOST
  compose up -d --build --remove-orphans
  wait_healthy
}

up_tunnel() {
  set_var PILOT_MODE tunnel
  if [ -n "$(get CLOUDFLARE_TUNNEL_TOKEN)" ]; then
    set_var TUNNEL_COMMAND "tunnel --protocol http2 run"
  else
    set_var TUNNEL_COMMAND "tunnel --protocol http2 --url https://gateway:443 --no-tls-verify"
  fi
  compose up -d --build --remove-orphans
  if [ -z "$(get CLOUDFLARE_TUNNEL_TOKEN)" ]; then
    local url=""
    for _ in $(seq 1 60); do url=$(quick_url); [ -n "$url" ] && break; sleep 2; done
    [ -n "$url" ] || { echo "no trycloudflare URL in the tunnel log; see: docker compose -p cloudlabs-pilot logs tunnel" >&2; exit 1; }
    if [ "$(get PUBLIC_HOST)" != "${url#https://}" ]; then
      set_var PUBLIC_HOST "${url#https://}"
      compose up -d api
    fi
  fi
  wait_healthy
  # The public name exists before the connector is through; without a registered connection visitors only get
  # Cloudflare error 1033. cloudflared needs outbound port 7844 (no fallback to 443), which some networks block.
  local registered=""
  for _ in $(seq 1 30); do
    if compose logs tunnel 2>/dev/null | grep -q "Registered tunnel connection"; then registered=1; break; fi
    sleep 2
  done
  if [ -z "$registered" ]; then
    echo "The tunnel could not reach Cloudflare: cloudflared needs OUTBOUND port 7844 (TCP), and this network" >&2
    echo "blocks it. Use the classroom network instead (scripts/pilot.sh up --lan), another network (a phone" >&2
    echo "hotspot), or ask the network admin to allow it. Details: docker compose -p cloudlabs-pilot logs tunnel" >&2
    exit 1
  fi
}

case "${1:-}" in
  up)
    init_state
    if [ "${2:-}" = "--lan" ]; then up_lan "${3:-}"; else up_tunnel; fi
    import_labs
    echo
    echo "CloudLabs pilot is up: https://$(get PUBLIC_HOST)"
    [ "$(get PILOT_MODE)" = "lan" ] && echo "(self-signed certificate: each browser shows a warning once; students choose Advanced → Continue)"
    echo "First time? scripts/pilot.sh admin you@college.edu \"Your Name\"   then sign in there."
    ;;
  admin)
    email=${2:?usage: scripts/pilot.sh admin EMAIL \"NAME\"}; name=${3:-Admin}
    compose exec -T -e EMAIL="$email" -e NAME="$name" api python -c "
import asyncio, os, secrets
from app.db import sessionmaker
from app.auth.routes import create_user
from app.models import Role
async def main():
    pw = secrets.token_urlsafe(12)
    async with sessionmaker()() as db:
        await create_user(db, os.environ['EMAIL'], os.environ['NAME'], Role.admin, pw, must_change_password=True)
        await db.commit()
    print('admin', os.environ['EMAIL'], 'temporary password:', pw)
asyncio.run(main())" | grep -v '^{'
    ;;
  url)
    echo "https://$(get PUBLIC_HOST)"
    ;;
  down)
    compose stop
    ;;
  *)
    sed -n '2,13p' "$0"
    exit 2
    ;;
esac
