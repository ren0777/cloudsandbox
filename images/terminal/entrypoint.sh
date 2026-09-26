#!/bin/bash
# Modes:
#   terminal (default): serve an interactive bash over ttyd; credential comes from TTYD_CREDENTIAL.
#   job <script>      : run a lab-pack script (setup / labtest) from /work and exit with its status.
set -euo pipefail
mkdir -p "$HOME/.aws"
cat > "$HOME/.aws/config" <<CFG
[default]
region = ${AWS_DEFAULT_REGION:-us-east-1}
output = json
endpoint_url = ${AWS_ENDPOINT_URL}
cli_pager =
CFG
cat > "$HOME/.aws/credentials" <<CRED
[default]
aws_access_key_id = ${AWS_ACCESS_KEY_ID:-testing}
aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY:-testing}
CRED
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
mode="${1:-terminal}"
if [ "$mode" = "job" ]; then
  script="${2:?script required}"
  cd /work
  exec bash "$script"
fi
cred="${TTYD_CREDENTIAL:?TTYD_CREDENTIAL required}"
unset TTYD_CREDENTIAL
exec ttyd --port 7681 --writable --credential "$cred" --max-clients 2 --ping-interval 20 \
     -t disableLeaveAlert=true bash --login
