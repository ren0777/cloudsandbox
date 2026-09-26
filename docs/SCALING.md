# Scaling CloudLabs from a laptop to college servers

CloudLabs runs on one machine or on a fleet of runner servers without code changes. How to deploy either shape:
`docs/DEPLOYMENT.md`. Measured capacity: `docs/LOADTEST.md`.

## What is in place (phase 7)
- **Runner fleet** (`runtime/fleet.py`). Runners are registered with their own URL and HMAC secret (stored
  encrypted), and registration succeeds only if the runner answers a signed capacity call with the same id. The
  control plane polls every runner concurrently for health, engine images, load, CPU and memory. One missed beat
  doesn't take a runner out of service; 90 s without a good heartbeat does.
- **Scheduler** (`runtime/scheduler.py`). A new lab goes to a healthy, non-draining, engine-compatible runner with a
  free seat, least-loaded first. Selection is serialised by one transaction advisory lock, so concurrent Starts
  can't over-fill a runner (tested with 12 concurrent Starts plus heartbeats, and with 32 real students).
- **No migration.** A session keeps its runner for life (`lab_sessions.runner_id`). Provision, reset, submit,
  console, grading and teardown all go to that runner.
- **Drain / maintenance.** A drained runner gets no new labs; running labs finish normally, and the runner shows
  *safe to stop* at zero. Retire removes it from scheduling and heartbeats. Drain, resume, register and retire are
  audited, including from the CLI.
- **Runner lost.** Unreachable for `CL_RUNNER_LOST_AFTER_S` (default 300 s): its active labs fail as `runner_lost`
  (no attempt used) and graded ones are closed. Nothing is reported alive or recreated elsewhere. Leftovers are
  removed when it returns.
- **Cross-host data path.** Runners on other servers run in `gateway` mode. The runner, not the API, attaches to
  each sandbox network and forwards that sandbox's emulator HTTP and terminal WebSocket at
  `/gw/<sandbox>/<token>/…` (per-sandbox random token, constant-time check, no generic proxy). The control plane
  treats endpoints as opaque URLs, so console, grading, probes and the terminal work unchanged. Single-host
  installs keep `direct` mode (decision D1).

## Still single-instance (next steps if one control-plane server isn't enough)
- **API replicas.** Rate limiters, progress throttles, terminal counts and the session event bus are in process
  memory. Move them to Redis before running several API containers behind the gateway.
- **Background work.** Provisioning, teardown, expiry and reconciliation run as asyncio tasks in the API. The
  reconciler is idempotent and CAS-based, so it could run in a separate worker (arq/Redis) or on several nodes.
- **mTLS to runners.** Today the runner channel is HMAC plus per-sandbox tokens on a private network (put a
  WireGuard tunnel between servers on untrusted networks). Native mTLS with pinned certificates (PLAN §10) plugs into
  `HttpRunnerClient` without changing the request format.

## Sizing guide
| Per sandbox | Limit | Measured (Floci, idle to working) |
|---|---|---|
| Emulator | 0.5 CPU, 384 MiB, 128 PIDs | about 20–30 MiB |
| Terminal | 0.5 CPU, 256 MiB, 128 PIDs | about 5–10 MiB |
| Provisioning | | about 12 s alone; about 47 s with 16 starting at once on 6 vCPUs |
| Grading (Submit) | | about 3 s; about 17 s with 16 concurrent labs on 6 vCPUs |

CPU during start-up and grading is the constraint, not RAM. Plan about 0.5 vCPU per concurrently starting lab. A
16-vCPU / 32 GB runner holds about 24 seats with room to spare. Configure Docker's `default-address-pools` for more
than about 25 sandboxes per host (DEPLOYMENT.md §1), and confirm with `python -m app.loadtest` on your own hardware.
