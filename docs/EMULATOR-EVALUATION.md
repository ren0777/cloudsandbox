# AWS emulator evaluation for CloudLabs (September 2026)

**Question:** which open-source emulator should run inside each student sandbox for S3, IAM, EC2, Lambda
and DynamoDB, given our architecture: one emulator container per student, non-root, read-only rootfs,
384 MiB, 0.5 CPU, no internet, and **no Docker socket inside the sandbox** (PLAN §12).

## Hands-on bake-off (same script, same hardening flags as the real runner)
The script is 26 operations across all five services (the S3 operations match what slice 1 uses). It runs from a separate container on an
`internal` network, and emulators are addressed by container IP as in production.

| | **Moto 5.2.3** (current) | **Floci** (latest) | **MiniStack** (latest) |
|---|---|---|---|
| Starts under our hardening | ✅ | ✅ with `--tmpfs /app/data` + `FLOCI_STORAGE_MODE=memory` | ✅ |
| Score | **24 / 26** | **25 / 26** | **26 / 26** |
| S3 (10 ops) | 10/10 | 10/10 | 10/10 (by IP; fails if the host name is a bare alias like `emu`) |
| IAM (6 ops) | 5/6 (no `SimulatePrincipalPolicy`) | 6/6 | 6/6 |
| DynamoDB (3 ops) | 3/3 | 3/3 | 3/3 |
| EC2 metadata (4 ops) | 4/4 | 4/4 | 4/4 |
| Lambda create/get | 2/2 | 2/2 | 2/2 |
| Lambda **invoke runs code** | ❌ (needs Docker) | ❌ (needs Docker) | ✅ in-process worker, no Docker |
| Memory after the run | **238 MiB** | **34 MiB** | **66 MiB** |
| Image size | ~200 MB (ours) | 81 MB | 71 MB |
| Runs as root by default | no (our image) | yes, but runs fine as 10001 | yes, but runs fine as 10001 |

## Project health and licensing
| | License | Maturity | IAM policy *enforcement* | Real EC2 / Lambda |
|---|---|---|---|---|
| **Moto** | Apache-2.0 | Oldest and healthiest maintenance | "very basic", opt-in | EC2 metadata only; Lambda via Docker |
| **Floci** | MIT | ~25k stars, 100+ contributors, 2.1.0 (pinned), big test suite | Permissive; S3 auth opt-in | via Docker socket |
| **MiniStack** | MIT | ~4.7k stars | not enforced | Lambda in-process; EC2 metadata (containers via Docker) |
| LocalEmu | Apache-2.0 | young LocalStack fork (~190 stars), heavy image | yes (`IAM_ENFORCEMENT=1`) | via Docker socket |
| fakecloud | **AGPL-3.0** | strongest IAM fidelity, 23 services | full | Lambda via Docker; no EC2 |
| kumo | MIT | Go single binary, one maintainer | — | — |

## Findings
1. **No emulator gives real EC2 instances or Lambda code execution without a Docker socket**, except
   MiniStack's in-process Lambda. Mounting the host Docker socket into a student sandbox would give students
   control of the host, so it's ruled out. Real EC2 "instance shells" stay a **runner-managed** feature, as
   planned (the runner is the only trusted Docker holder).
2. **Nobody enforces IAM well except fakecloud (AGPL) and LocalEmu (unproven).** CloudLabs keeps its own
   IAM policy evaluator for grading (`simulated` support level), as planned.
3. **Floci's footprint is the biggest win for a college:** about 7× less RAM per sandbox than Moto means far
   more concurrent students per server.
4. Our architecture already isolates most of the emulator choice: a per-emulator capability file
   (`runtime/capabilities/<emulator>.yaml`), `runtime.emulator` in `lab.yaml`, boto3-based evidence collectors,
   and contract tests. What is still hard-coded is in the **runner**: one emulator image, port 5000 and the
   Moto healthcheck. Supporting several engines means a small, contained change there: an
   `emulators: {name → image, port, tmpfs, env}` table, with `create_sandbox` taking the lab's emulator name.
   The grader, console, UI and state machine don't change. **(Implemented: STATUS D8.)**

## Recommendation
- **Primary engine: Floci.** Adopt it before building IAM/DynamoDB/EC2 labs (next phase). Wrap it in a
  CloudLabs image (non-root, tmpfs data dir, memory storage, healthcheck on :4566). Add
  `capabilities/floci.yaml` and run the existing contract tests, labtest and E2E against it.
- **Keep Moto** as a verified fallback adapter (`runtime.emulator: moto`); it's slice 1's proven baseline.
- **Lambda:** evaluate MiniStack through the same abstraction **only if** Floci can't safely run the required
  Lambda lab behaviour without giving the sandbox Docker access (PLAN emulator strategy §4), never just for having more
  features. If used, student code runs inside that student's own isolated, non-root, offline emulator container.
- Don't adopt LocalEmu or fakecloud now. Revisit if IAM-*enforcement* labs ("fix the access denied error")
  become a requirement.

Reproduce: `bash tools/emulator-bakeoff/bakeoff.sh`. Re-run on every emulator
upgrade, since these projects change weekly.

---

## Promotion decision (2026-09-25): **Floci is the default engine; Moto stays a supported regression backend**

### How it was integrated
- Through the emulator abstraction only (STATUS D8/D9): runner `EmulatorSpec` table + `cloudlabs.engine`
  label; API `EmulatorAdapter` registry (`app/runtime/emulators.py`); `lab_sessions.engine`; per-engine
  capability files `capabilities/{moto,floci}.yaml`. Grader checks, evidence format, FastAPI contracts,
  lab definitions (`runtime.emulator: default`) and the student UI contain no engine-specific code.
  Engine names never reach students (tested).
- Floci runs from `images/emulator-floci` (pinned 2.1.0), non-root, read-only rootfs + tmpfs, memory
  storage, **no Docker socket**.

### Gate: every criterion run against Floci (and Moto, for regression)
| Criterion | Test(s) | Moto | Floci |
|---|---|---|---|
| Moto baseline before any Floci work | runner 9 · API 163 · labtest · E2E 3 | ✅ | n/a |
| Sandbox isolation + hardening (non-root, read-only, limits, no egress, no cross-sandbox reach, reset, jobs, cleanup) | `services/runner/tests/test_docker_driver.py` (engine-parametrized) — 12 passed | ✅ | ✅ |
| S3 contract: every declared `supported` op | `test_contract_for_every_declared_supported_s3_operation[engine]` | ✅ | ✅ |
| Labtest 0 / 50 / 100 | `test_labtest_scores_on_real_runtime[engine]` + `python -m app.labtest` | ✅ | ✅ |
| GUI+CLI journey, grading, evidence, instructor view, **session freeze** (terminal closed with `submitted`, console 409, no new ticket), no private files, no egress, cleanup | `test_student_journey_gui_and_cli[engine]` | ✅ | ✅ |
| Terminal ticket rules (origin, single use, expiry, max 2, reset close) | `test_terminal_ticket_rules[engine]` | ✅ | ✅ |
| Full CloudLabs API suite with the engine as platform default | 174 passed (`CL_DEFAULT_EMULATOR=floci`) | ✅ (163 before the adapter tests) | ✅ |
| Browser E2E (Playwright) | `apps/web/e2e/journey.spec.ts` 3/3; DB confirms `engine=floci`, image digest = pinned Floci image | ✅ | ✅ |
| Engine selection rules (default must be valid on every engine; ownership-scoped capability catalogue; engine never exposed) | `tests/test_emulators.py` | ✅ | ✅ |

Known flake: one run of the engine-independent `test_append_only_tables_reject_update_and_delete[attempts]`
failed once in a full run (not reproduced in 6 isolated runs, a module run or the next full run). It is tracked
in STATUS.md and doesn't involve the emulator.

### Why Floci
1. **Passed every gate criterion** under the full CloudLabs sandbox hardening, with the same results as Moto.
2. **Capacity:** about 34 MiB per emulator versus about 238 MiB for Moto in the bake-off, so roughly 7× more
   concurrent students per server, which is the main constraint for a college deployment.
3. **Faster sandboxes:** a measured Floci session reached READY in 7.4 s (Moto sessions about 12 s on the same laptop).
4. **Broader service surface for the roadmap** (IAM `SimulatePrincipalPolicy`, DynamoDB, EC2 metadata) under
   an MIT license with an active community.

### What Moto keeps
Moto stays in the engine table and in every parametrized real-runtime test, so any regression in either
engine is caught. Individual labs may pin `runtime.emulator: moto` if they need Moto-specific behaviour.

### Lambda decision (2026-09-25): **MiniStack, only for labs that execute code**
Probe: `tools/emulator-bakeoff/lambda_probe.py` runs the same script on every engine inside a hardened sandbox
(non-root, read-only rootfs, cap_drop ALL, no egress, **no Docker socket**): create role + function, update
code/configuration, invoke (hello, env-driven total, raised error), delete.

| Engine | Function management | Invoke (execute code) | Notes |
|---|---|---|---|
| Floci 2.1.0 | ✔ | ✘ "Failed to start Lambda container" | Invoke launches a Docker container per function |
| Moto 5.2.3 | ✔ | ✘ "error running docker" | same: Lambda execution needs Docker |
| MiniStack 1.5.16 | ✔ | ✔ correct results and errors, ~10–12 s per invoke | runs the handler in-process; needs `endpoint_by_ip` (host-alias quirk) |

Giving a sandbox the Docker socket would break the isolation model (PLAN §10/§12), so Floci cannot *safely*
execute the Lambda lab behaviour. Per the emulator strategy, MiniStack is therefore added as a **specialised**
engine (`emulators.SPECIALISED`), not a default:
- Labs that need code execution pin `runtime.emulator: ministack` (`labs/lambda-basics`). Its capability file
  declares only what was verified (Lambda management + `Invoke`, IAM role basics); S3/DynamoDB/EC2 are absent,
  so the console shows only Lambda and imports needing anything else are rejected.
- On Floci/Moto, Lambda management works and `lambda:Invoke` is `unsupported`: the console's Test tab is
  labelled unavailable, the API answers `409 not_in_simulator`, and a `default` lab using
  `lambda.invoke_returns` is rejected at import.
- `lambda.invoke_returns` runs as a *probe* during evidence capture (the function's output becomes evidence),
  so grading stays a pure function of stored evidence.
- Verified: contract (every declared Lambda op) on Floci, Moto and MiniStack; labtest 0/45/100 on MiniStack;
  console tests; E2E `e2e/lambda.spec.ts`.
