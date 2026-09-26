# Load testing CloudLabs

`python -m app.loadtest --students N` (run inside the `api` container of a demo-mode stack) drives the **real HTTP
API** the way a class does:

1. An admin creates a course, imports an N-student roster (temporary passwords) and assigns the S3 lab. Every
   student signs in and sets a password.
2. The whole class presses **Start at the same moment**. Students who get `capacity_full` retry with the web app's
   back-off (3 → 5 → 8 → 12 s ± 20 %) until a seat frees up.
3. Each student waits until READY, creates a bucket in the console, **Submits**, and waits for TERMINATED.
4. Every 3 s the runners' read-only `/v1/stats` is sampled (memory per sandbox, host memory).
5. Afterwards every sandbox of the run must be gone from every runner.

Reported: provisioning latency (created → READY), grading latency (Submit round trip), capacity rejections,
failures by reason, peak sandbox memory, host memory headroom, cleanup success and transport retries. The command
exits non-zero on any failure or leftover sandbox. Demo reset removes everything it created.

## Results (2026-09-25, development laptop)

Host: Windows 11 laptop, Docker Desktop / WSL2 VM with 6 vCPUs and 5.8 GiB RAM. Two runners on the same Docker host:
`runner-local-1` (direct mode) and `runner-local-2` (**gateway mode**, as a remote server would run). Engine: Floci.

| Students | Runners (seats) | Wall time | First wave started / full | Capacity rejections (incl. retries) | Provisioning p50 / p95 / max | Grading p50 / p95 / max | Failures | Cleanup |
|---|---|---|---|---|---|---|---|---|
| 16 | 2 (8) | 48 s | 8 / 5 | 20 | 20.8 / 21.3 / 21.3 s | 3.0 / 3.4 / 3.5 s | **3** (deadlock, fixed) | 13/13 |
| 24 | 2 (8) | 89 s | 8 / 16 | 71 | 11.8 / 26.0 / 26.1 s | 3.4 / 5.4 / 6.0 s | 0 | 24/24 |
| 32 | 2 (16) | 160 s | 16 / 16 | 63 | 47.0 / 61.6 / 62.0 s | 17.0 / 23.7 / 24.1 s | 0 | 32/32 |

Memory (32-student run): 8 sandboxes per runner used 280–290 MiB in total. Each Floci sandbox (emulator and
terminal) used **29–33 MiB on average, 38.5 MiB at most**, far below its limits (384 + 256 MiB). The lowest free host
memory was 2.66 GiB of 5.8 GiB.

### Reading the numbers
- **Seats, not memory, are the limit.** Idle labs are light. The cost is CPU while emulators start and while
  grading reads state. With 16 labs starting at once on 6 vCPUs, provisioning rose from about 12 s to about 47 s
  and grading from about 3 s to about 17 s. Nothing failed, but it was slow.
- **Rule of thumb:** about 0.5 vCPU per concurrently *starting* lab keeps provisioning under 20 s. A 16-vCPU /
  32 GB runner comfortably holds about 24 seats (memory is not the limit). Measure on your own hardware before
  setting `RUNNER_MAX_SANDBOXES`, and remember Docker's address pools (DEPLOYMENT.md §1) above about 25 sandboxes
  per host.
- Capacity rejections are expected when a class outnumbers the seats. Students see "All lab seats are in use,
  retrying…" and get in as seats free up. In the 24-student run everyone finished within 90 s on 8 seats.

## What the load test found (all fixed, with regression tests)

| Finding | Symptom | Fix | Test |
|---|---|---|---|
| Scheduler deadlock | 3 of 16 simultaneous Starts answered 500. Start locked runner rows `FOR UPDATE` while heartbeats updated the same rows in another order | Selection now runs under one transaction advisory lock and runner rows are only read. Heartbeats update rows in id order | `test_fleet.py::test_concurrent_starts_never_overfill_a_runner` (runs heartbeats during the burst) |
| Password hashing blocked the event loop | 32 sign-ins at once froze every other request | argon2id runs in bounded worker threads with the OWASP profile (19 MiB, t=2, p=1); old hashes upgrade at next sign-in | `test_auth_and_policy.py::test_password_hashing_does_not_block_the_event_loop` |
| Single missed heartbeat took a runner out | Under provisioning load a 10 s capacity call timed out and students got `runtime_unavailable` | A runner stays schedulable until its last good heartbeat is older than 90 s; the runner caches image checks for 30 s | `test_fleet.py::test_heartbeat_records_health_engines_and_memory` |
| Reattach loop raced sandbox destroy | A graded session stayed TERMINATING: the runner re-attached the API to a network being destroyed, and Docker kept a stale endpoint | Reattach takes the sandbox lock and skips half-destroyed sandboxes; destroy retries, and an empty network Docker won't remove is recorded as *leaked* (no seat, shown on Runtime) | runner `test_reattach_never_blocks_destroy` |

The driver itself retries transport resets like a browser (0 were needed in the final runs) and drops idle
keep-alive connections before uvicorn's 5 s idle timeout.

## Running it

```bash
docker compose -f infra/docker-compose.yml --profile multi up -d runner2        # optional second runner
RUNNER_SECRET=dev-runner2-secret-change-me docker compose -f infra/docker-compose.yml exec -e RUNNER_SECRET api \
  python -m app.runtime.fleet register runner-local-2 http://runner2:7070
docker compose -f infra/docker-compose.yml exec api python -m app.demo reset
docker compose -f infra/docker-compose.yml exec api python -m app.loadtest --students 24 --out /tmp/lt.json
```
Seats per runner come from `RUNNER_MAX_SANDBOXES` / `RUNNER2_MAX_SANDBOXES`.
