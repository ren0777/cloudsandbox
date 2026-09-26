#!/usr/bin/env bash
# Run each emulator under CloudLabs sandbox hardening and execute bakeoff.py against it.
SCR="$(cd "$(dirname "$0")" && pwd -W 2>/dev/null || pwd)"
export MSYS_NO_PATHCONV=1
run() {
  name=$1 image=$2 port=$3 mode=$4 extra=$5
  net=bake-$name
  docker rm -f bake-emu-$name >/dev/null 2>&1; docker network rm $net >/dev/null 2>&1
  docker network create --internal $net >/dev/null
  if [ "$mode" = hardened ]; then
    flags="--user 10001:10001 --read-only --tmpfs /tmp:size=32m,uid=10001 --memory 384m --memory-swap 384m --pids-limit 128 --cpus 0.5 --cap-drop ALL --security-opt no-new-privileges"
  else
    flags="--memory 384m"
  fi
  echo "=================== $name ($mode) $image"
  docker run -d --name bake-emu-$name --network $net --network-alias emu $flags $extra $image >/dev/null
  sleep 8
  state=$(docker inspect -f '{{.State.Status}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}}' bake-emu-$name)
  echo "container: $state"
  if ! echo "$state" | grep -q running; then docker logs bake-emu-$name 2>&1 | tail -5; else
    docker run --rm --network $net -v "$SCR:/b:ro" --entrypoint python cloudlabs/api:dev /b/bakeoff.py http://emu:$port 2>&1 | tail -30
    [ "$name" = ministack ] && docker logs bake-emu-$name 2>&1 | grep -iE "error|traceback|exception|denied|read-only" | head -8
    docker stats --no-stream --format 'memory: {{.MemUsage}}' bake-emu-$name
  fi
  docker rm -f bake-emu-$name >/dev/null; docker network rm $net >/dev/null
}
run moto cloudlabs/emulator:dev 5000 hardened
run floci floci/floci:latest 4566 hardened "--tmpfs /app/data:size=64m,uid=10001 -e FLOCI_STORAGE_MODE=memory"
run ministack ministackorg/ministack:latest 4566 hardened
