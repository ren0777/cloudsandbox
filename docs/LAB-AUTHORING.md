# Writing a CloudLabs lab pack

A lab pack is a folder under `labs/`:

```
labs/my-lab/
  lab.yaml            # the definition (schema_version 1) — students see a redacted view of it
  public/             # optional: setup scripts/assets (sent to the runner; never secret)
  private/            # solution.sh, partial.sh, expected.yaml, notes — NEVER reaches students
```

## lab.yaml (schema_version 1)
```yaml
schema_version: 1                 # required; unknown versions are rejected
id: s3-basics                     # slug
version: 1.0.0                    # semver; a changed lab needs a new version (versions are immutable)
title: "Mission 1: CloudCafé goes online"
summary: One line for the lab card.
story: |                          # markdown-lite: paragraphs, **bold**, `code`; may use variables
  Your bucket is **{{ bucket }}**.
services: [s3]                    # s3 | dynamodb | iam | ec2 available; lambda later
runtime: {emulator: default}      # platform default engine; name an engine only if a lab truly needs it
duration_minutes: 45              # hard TTL (capped at 120)
idle_minutes: 20                  # optional (clamped to 10–30)
max_attempts: 3                   # default for new assignments
variables:                        # rendered per student; student_short_id is built in
  bucket: "cafe-{{ student_short_id }}-site"
requires: [s3:CreateBucket, s3:PutBucketVersioning]   # emulator operations students need
resources:                        # optional; clamped to admin caps
  emulator: {memory_mib: 512}
setup: {script: setup.sh, timeout_s: 60}             # optional legacy break-fix setup, file in public/
break_actions: []                                    # break_fix: typed starting-state actions (preferred)
baseline: {expected_score: "0.00"}                   # break_fix: score the broken state should earn
tasks:
  - id: create-bucket
    title: "Create the bucket {{ bucket }}"
    description: Shown under the title.
    hints: ["Terminal: aws s3 mb s3://{{ bucket }}"]
    marks: 25
    scoring: all                  # all (default): all checks must pass | proportional: by weight
    checks:
      - {type: s3.bucket_exists, bucket: "{{ bucket }}"}
      - {type: s3.object_content_type, bucket: "{{ bucket }}", key: index.html,
         content_type: text/html, hidden: true, weight: 1, feedback: "Custom failure message"}
```

## Available checks (slice 1)
| Type | Params | Passes when |
|---|---|---|
| `s3.bucket_exists` | `bucket` | the bucket exists |
| `s3.versioning` | `bucket`, `status` (Enabled/Suspended) | versioning status matches |
| `s3.object_exists` | `bucket`, `key`, `min_size` | the object exists and is at least `min_size` bytes |
| `s3.object_content_type` | `bucket`, `key`, `content_type` | the Content-Type matches |
| `s3.bucket_tag` | `bucket`, `key`, `value` | the tag is set to the value |
| `dynamodb.table_exists` | `table` | the table exists |
| `dynamodb.key_schema` | `table`, `partition_key`, `partition_type` (S/N/B), `sort_key`?, `sort_type` | the primary key matches exactly (no sort key unless given) |
| `dynamodb.billing_mode` | `table`, `mode` (PAY_PER_REQUEST/PROVISIONED) | the capacity mode matches |
| `dynamodb.item` | `table`, `key` {attr: value}, `attributes` {attr: value} | an item with that key has those values (numbers compared canonically) |
| `dynamodb.attribute_type` | `table`, `key`, `attribute`, `attribute_type`, `value`? | the attribute has that DynamoDB type (e.g. a quantity stored as N, not S) |
| `dynamodb.item_count` | `table`, `min` | the table holds at least `min` items |

| `iam.user_exists` / `iam.group_exists` | `user` / `group` | the identity exists |
| `iam.user_in_group` | `user`, `group`, `expect` (present/absent) | the user is (or, with `absent`, is not) a member. A deleted user counts as absent |
| `iam.policy_attached` | `principal` (`user:`/`group:`/`role:` + name), `policy` (name or ARN), `expect` (present/absent) | the managed policy is (or is no longer) attached to that principal |
| `iam.role_trusts` | `role`, `service` (e.g. `lambda.amazonaws.com`) | the trust policy lets the service assume the role |
| `iam.policy_allows` | `principal`, `action`, `resource`, `expect` (allow/deny), `absent_ok` (default false) | the **CloudLabs policy evaluator** reaches that decision (identity policies of the user + its groups, or the group/role; explicit deny wins; conditions aren't evaluated) |

| `ec2.instance` | `name` (Name tag), `state` (running/stopped/any), `instance_type`?, `key_name`? | a non-terminated instance with that Name matches |
| `ec2.instance_tag` | `name`, `key`, `value` | the instance has the tag |
| `ec2.instance_security_group` | `name`, `group` | the instance uses the security group |
| `ec2.security_group_rule` | `group`, `protocol`, `port`, `cidr`, `expect` (present/absent) | an inbound rule covers that port from exactly that CIDR (an "All traffic" rule covers every port) |
| `ec2.key_pair_exists` | `key` | the key pair exists |
| `ec2.running_instance_count` | `min`, `max` | the number of running instances is within the bounds (use `min: 1` so an empty sandbox can't pass) |

| `lambda.function` | `name`, `runtime`?, `handler`?, `role_name`?, `env` {K: V}?, `memory_min`?, `timeout_min`? | the function exists with those settings |
| `lambda.invoke_returns` | `name`, `payload` (event), `expect` | invoking the function with `payload` returns a response containing `expect` (dicts match as a subset, numbers with float tolerance) |

`audit.*` is reserved and rejected with "not available yet".

**Lambda labs and probes:** `lambda.invoke_returns` declares a *probe*. During evidence capture (baseline,
progress, submit) the collector first invokes the function with each distinct payload and stores the result;
grading then reads only the stored evidence. Invoking needs an engine that executes code, so such labs must
pin `runtime: {emulator: ministack}` (`lambda:Invoke` is unsupported on Floci and Moto, and a `default` lab
using it is rejected at import). The MiniStack capability file has no S3/DynamoDB/EC2, so keep those labs
Lambda-only. Invocations take ~10 s each, so use at most a few probes. Use a hidden probe (for example an
empty input) to catch hard-coded answers.

**Engine-neutral EC2 labs:** AMI IDs differ between engines, so never check or hard-code them. In
private scripts, discover one with `aws ec2 describe-images --owners amazon --query "Images[0].ImageId" --output text`.
Instances are simulated records: they have a state but no running machine. Check params are validated **after** rendering with a sample student, so type errors show up at
import.

## Break-fix labs
Set `kind: break_fix` and describe the broken starting state with **typed break actions** in `lab.yaml`.
Actions are declarative data, never instructor-written shell: each is a safe operation with a typed
parameter model, and CloudLabs compiles them into the setup that runs in a short-lived job container before
the lab starts and again on **Reset**, with the AWS CLI pointed at the sandbox and every variable exported
in upper case (`$GROUP`, `$STUDENT_SHORT_ID`, …). Tasks then check the **repaired final state**.

```yaml
kind: break_fix
break_actions:
  - {type: iam.create_group, group: "{{ group }}"}
  - {type: iam.attach_managed_policy, target_type: group, target: "{{ group }}", policy: AdministratorAccess}
  - {type: s3.disable_versioning, bucket: "{{ bucket }}"}
  - {type: ec2.authorize_ingress, group: "{{ group }}", protocol: tcp, port: 22, cidr: 0.0.0.0/0}
  - {type: lambda.remove_env_var, function: "{{ function }}", name: TABLE_NAME}
baseline: {expected_score: "0.00"}   # or e.g. "40.00" when the lab intentionally starts partly correct
```

The catalogue (services, action types, parameter JSON Schema) is `GET /api/instructor/builder/break-actions`;
the Lab Builder's **Starting state** tab generates its forms from it and shows the Broken State Summary. The
catalogue covers IAM (create group/user, membership, attach/detach a managed policy), S3 (create bucket,
versioning, bucket policy, public access, tags), EC2 (security group, ingress rules) and Lambda (remove an
environment variable); new typed actions are added in `services/api/app/breakfix/`. Import-time validation
rejects an unknown action, bad parameters, a service not listed in `services`, and any action an engine
cannot perform.

Rules of thumb:
- The untouched broken state must score `baseline.expected_score` (0 unless the lab starts partly correct);
  `private/expected.yaml`'s `empty` must match it, and it must be **below full marks**. labtest runs setup
  first.
- labtest also **resets** the sandbox and re-scores it: Reset must reproduce the identical baseline.
- Grade the outcome, not the steps: `expect: absent` for "remove this", `iam.policy_allows` with
  `expect: deny` for "can no longer", `absent_ok: true` when deleting the principal is a valid fix.
- Add at least one check that a lazy "fix" fails, such as deleting everything or granting `*`. Hidden checks
  work well here.
- The compiled setup isn't secret (it describes the problem). Keep solutions in `private/`.
- The baseline is captured after setup, so an untouched auto-submit doesn't use an attempt.

Legacy packs (like `labs/iam-breakfix`) may instead carry a `setup` script in `public/`; it runs the same
way. A lab uses `break_actions` **or** a setup script, never both; the Lab Builder carries a legacy setup
script read-only.

## The simulator is honest
Every operation in `requires`, and every operation a check reads, must be `supported` or `simulated` in
`services/api/app/runtime/capabilities/<engine>.yaml`. A lab on `runtime.emulator: default` must be valid
on **every** engine (Floci and Moto), so changing the platform default can never break it. Import fails
otherwise. Known limitations (IAM not
enforced, no website endpoint, in-memory state, …) are listed in that file.

## Private material and testing
`private/solution.sh` and `private/partial.sh` get every variable exported in upper case (`$BUCKET`,
`$STUDENT_SHORT_ID`) and run with the AWS CLI already pointed at the sandbox. `private/expected.yaml`:
```yaml
empty: "0.00"
partial: "50.00"
solution: "100.00"
```
Test on the real runtime (fresh sandbox per scenario, job containers, pure grading):
```bash
docker compose -f infra/docker-compose.yml exec -T api python -m app.labtest /labs/my-lab            # every engine
docker compose -f infra/docker-compose.yml exec -T api python -m app.labtest --engine floci /labs/my-lab
```
Import (creates an immutable lab version; the same version with different content is rejected):
```bash
docker compose -f infra/docker-compose.yml exec -T api python -m app.labs.importer /labs/my-lab
```
Assignments pin a lab version, so editing a pack never changes what running assignments are graded against.

## Instructor Lab Builder (browser)

Instructors can create, test and publish labs from the browser instead of editing files on the server
(`/instructor/labs`, phase 8). It writes the same schema-v1 packs described above.

- **New / Templates / Clone / Import.** *New* opens a gallery: **Start from scratch** (a small S3 lab) or a
  **template** — a working built-in lab offered as a starting point (S3 basics, DynamoDB basics, IAM least
  privilege, EC2 web server, Lambda serverless, IAM break-fix). A template becomes **your own** lab: new id
  `<title-slug>-<your short id>`, version `1.0.0`, your title, with all tasks, checks, reference solution and
  expected scores carried over (`GET /api/instructor/builder/templates`). *Clone* copies any lab version you
  can see: a built-in mission or another author's lab becomes a new id `<id>-<your short id>` at `1.0.0`
  (titled "… (copy)"), while cloning **your own** lab prepares its next minor version (same id, e.g.
  `1.1.0`). *Import* accepts a `.tar.gz`/`.tar` pack exported from the builder.
- **Editor.** Overview (including variables), Tasks and Scripts are a form builder; the check parameter
  forms are generated from the grader's Pydantic models (`GET /api/instructor/builder/check-types`), so a
  field can never drift from what grading accepts. The **YAML** tab is the same draft as `lab.yaml` and is
  editable (aliases are refused; comments are not kept). **Preview** shows the redacted student view with
  sample variables — never checks or private files.
- **Editable vs read-only files.** Only `private/solution.sh`, `private/partial.sh`,
  `private/expected.yaml` and `private/notes.md` are editable. Any other file from a clone or import (for
  example a break-fix `setup.sh`) is carried unchanged and shown read-only; v1 does not author setup scripts.
- **Preview sandbox.** From the Starting state tab, *Launch preview sandbox* opens the declared starting state
  in a **real isolated sandbox** — the same sandbox a student lab gets — inspectable in the AWS-style console
  and the browser terminal. **Reset** re-runs the declared typed actions, so the broken state comes back
  identically. A preview is **not a session**: it creates no attempt, grade, XP, badge or leaderboard event,
  and only the draft's author (or an admin) can see it.
- **Autosave and undo.** Every edit is saved about a second after you stop typing; the header shows
  *Saving… / Saved / Save failed*, and a failed save offers *Try again* (it is never retried in a loop).
  **Undo**/**Redo** (Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z) walk your edits in meaningful steps — a burst of typing
  counts as one — and switching tabs or leaving the page never discards work. If the draft is saved
  somewhere else meanwhile (another tab, a test run) the builder refuses to overwrite it and offers
  *Reload draft* instead; published, immutable versions are never touched.
- **Run this check.** On the Tasks tab each check can be run on its own against the running preview
  sandbox. It returns the grader's own **expected / actual, pass/fail, marks possible and message** — the
  same check function and evidence capture final grading uses — without creating an attempt, grade, badge
  or evidence row. A check the engine cannot answer says so and names the operation; runs are spaced about
  a second apart, and an invalid pack reports the same row-level errors as the validation panel.
- **Publish readiness.** The Test & publish tab lists every gate before the Publish button: schema/services/
  ownership validation, engine capability support, the baseline against `baseline.expected_score`, the
  reference solution at full marks, Reset reproducing the baseline, and a passing test of the **current**
  content — each with row-level errors. Publishing is enabled only when every row passes.
- **Validation** is always shown, and each error is placed on the row that caused it (a task/check/field, or
  a file). Drafts save even while invalid — they are work in progress.
- **Test & publish gate.** A lab can only be published after a test run in **real sandboxes** on every engine
  the lab may run on: an untouched sandbox must score its baseline (`baseline.expected_score`, default `0`; a
  break-fix lab may start partly correct), `private/partial.sh` (if present) must reach the score in
  `expected.yaml`, and the reference solution must score full marks. For a break-fix lab the run also resets
  the sandbox and re-scores it, so Reset must reproduce the baseline. The run is asynchronous and per-check
  results appear as they land. Publishing is allowed only while the last test passed on the **current**
  content hash — editing even `notes.md` invalidates it and requires a new run.
- **Publishing** imports an immutable lab version owned by the author and records `lab.published`. The lab is
  **private to its author (and admins)** until the author marks it *shared*, which makes it visible to every
  instructor to assign or clone. Versions are immutable: editing a published lab means cloning it into a new
  draft with a new version.
- **Export/import** round-trips a pack as a deterministic `.tar.gz` (staff only). Private files are included
  and never offered to students.

The CLI equivalents (`app.labtest`, `app.labs.importer`) remain and are what CI uses.
