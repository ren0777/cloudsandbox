#!/usr/bin/env bash
# M44 evaluation: run VPC / SQS / SNS probes on every engine under the same hardening as a Stackora
# sandbox (mirrors services/runner/app/docker_driver.py: non-root 10001, read-only rootfs, tmpfs /tmp,
# 384 MiB / 0.5 CPU / 128 pids, cap-drop ALL, no-new-privileges, internal network with no egress).
# Uses the pinned CloudLabs emulator images (what production actually ships), not upstream :latest.
# Results land in tools/emulator-bakeoff/m44-results/<engine>.txt.
set -uo pipefail
SCR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SCR/m44-results"
mkdir -p "$OUT"

run() {
  name=$1 image=$2 port=$3 extra=$4
  net=m44-$name
  log=$OUT/$name.txt
  docker rm -f m44-emu-$name >/dev/null 2>&1
  docker network rm $net >/dev/null 2>&1
  docker network create --internal $net >/dev/null
  flags="--user 10001:10001 --read-only --tmpfs /tmp:size=32m,uid=10001 --memory 384m --memory-swap 384m
         --pids-limit 128 --cpus 0.5 --cap-drop ALL --security-opt no-new-privileges"
  {
    echo "# M44 probe: $name  image=$image  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# hardening: $flags $extra"
    docker run -d --name m44-emu-$name --network $net --network-alias emulator $flags $extra $image >/dev/null
    state=$(docker inspect -f '{{.State.Status}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}}' m44-emu-$name)
    echo "# container: $state"
    if ! echo "$state" | grep -q running; then
      docker logs m44-emu-$name 2>&1 | tail -20
      echo "# EMULATOR DID NOT START"
    else
      for _ in $(seq 1 60); do
        health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' m44-emu-$name)
        [ "$health" = healthy ] && break
        [ "$health" = unhealthy ] && break
        sleep 1
      done
      echo "# health: $health"
      ip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$net\").IPAddress}}" m44-emu-$name)
      docker run --rm --network $net -v "$SCR:/b:ro" --entrypoint python cloudlabs/api:dev \
        /b/m44_probe.py "http://$ip:$port" 2>&1
      echo "# memory: $(docker stats --no-stream --format '{{.MemUsage}}' m44-emu-$name)"
      echo "# errors in emulator log:"
      docker logs m44-emu-$name 2>&1 | grep -iE "error|traceback|exception" | head -10
    fi
  } | tee "$log"
  docker rm -f m44-emu-$name >/dev/null 2>&1
  docker network rm $net >/dev/null 2>&1
}

echo "Images evaluated:" | tee "$OUT/versions.txt"
for img in cloudlabs/emulator:dev cloudlabs/emulator-floci:dev cloudlabs/emulator-ministack:dev; do
  echo "  $img $(docker image inspect -f '{{index .Config.Labels "cloudlabs.moto_version"}}{{index .Config.Labels "cloudlabs.floci_version"}}{{index .Config.Labels "cloudlabs.ministack_version"}}' $img 2>/dev/null) $(docker image inspect -f '{{.Id}}' $img | cut -c8-19)" | tee -a "$OUT/versions.txt"
done

run moto cloudlabs/emulator:dev 5000 ""
run floci cloudlabs/emulator-floci:dev 4566 "--tmpfs /app/data:size=64m,uid=10001 -e FLOCI_STORAGE_MODE=memory"
run ministack cloudlabs/emulator-ministack:dev 4566 ""

echo "done"
