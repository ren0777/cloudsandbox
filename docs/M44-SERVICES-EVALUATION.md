# VPC, SQS and SNS on every emulator — M44 preparation (September 2026)

**Question:** can Stackora teach **VPC**, **SQS** and **SNS** on Floci (platform default), Moto
(regression backend) and MiniStack (specialised engine) under the same locked-down sandbox, and which
engine should be the default **per service**?

This is *preparation only* for SNS: no student UI, no lab packs, no template, no API endpoints and **no
change to the production defaults** were made. The deliverable is evidence, capability declarations,
contract tests and the proposals below. **VPC and SQS have since been implemented** from these proposals
— see the implementation status below; SNS remains a proposal.

## VPC and SQS implementation status (landed 2026-09-28)

The VPC proposal is implemented end to end, using exactly this evaluation's operation set:

- `app/console/vpc.py`: 17 endpoints (overview, VPCs, subnets, route tables/routes/associations,
  internet gateways, security groups with rule editing), resources addressed by `Name` tags and
  capability-filtered through the adapter (`vpc` → boto3 `ec2`).
- `vpc` evidence collector + six checks (`vpc.exists`, `vpc.subnet`, `vpc.route`,
  `vpc.subnet_route_table`, `vpc.internet_gateway_attached`, `vpc.security_group_rule`); the architecture
  diagram gained a network map; VPC is free in the cost meter (as on AWS).
- `vpc-basics` (guided) and `vpc-breakfix` (typed `vpc.*` break actions, baseline 25) pass `app.labtest`
  on **moto and floci**, are seeded by the demo reset and appear as Lab Builder templates.
- `apps/web/components/vpc-console.tsx` + capability-gated nav; E2E `e2e/vpc.spec.ts` **2/2** (Mission 8
  scores 100; Mission 9 repairs the broken network in the console).
- Deviations worth recording: measurements changed three timeouts, because a CLI-driven break-action
  setup is ~20-30 AWS CLI calls: compiled setup cap 60 → **180 s**, `runner_timeout_s` 150 → **240 s**,
  gateway `proxy_read_timeout` 180 → **300 s**. The console orders named (lab) resources before the
  unnamed engine defaults, so create dialogs default to the student's own VPC/gateway.
- Engine quirks stayed where they belong: no check depends on ids, ARNs or `DependencyViolation`, and
  nothing outside the capability/adapter layer knows which engine runs.

SQS (same shape):

- `app/console/sqs.py`: queue list/detail, attributes, tags, send, poll, delete message, purge and delete
  queue; FIFO-aware creation. The console **poll** receives with `VisibilityTimeout=0`, so inspecting
  messages never steals them from another consumer or from grading.
- `sqs` evidence collector with an `sqs_peek` probe (`ReceiveMessage` visibility 0, up to 10 bodies) and
  four checks: `sqs.queue_exists`, `sqs.queue_attribute`, `sqs.queue_tag`, `sqs.message_present`.
- `sqs-basics` (guided; 0/35/100) and `sqs-breakfix` (a queue-attributes incident built from typed
  `sqs.*` break actions; baseline 20/70/100 and Reset reproduces it) pass labtest on **moto and floci**,
  are seeded by the demo reset and appear as templates.
- Console page + capability nav; E2E `e2e/sqs.spec.ts` **2/2** (create the order queue and send an order;
  restore the stuck queue's visibility timeout and delay).

## Scope and method

- **Same hardening as production** (`services/runner/app/docker_driver.py`): non-root `10001`, read-only
  rootfs, `--tmpfs /tmp:size=32m`, 384 MiB / 0.5 CPU / 128 pids, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, on an **internal** network (no egress, no Docker socket).
- **The pinned CloudLabs images are what was tested** (not upstream `:latest`):
  `cloudlabs/emulator:dev` = Moto 5.2.3, `cloudlabs/emulator-floci:dev` = Floci 2.1.0,
  `cloudlabs/emulator-ministack:dev` = MiniStack 1.5.16 (see `m44-results/versions.txt`).
- **Probes** (`tools/emulator-bakeoff/m44_probe.py`, driven by `m44_bakeoff.sh`): 68 semantic operations
  — 32 VPC, 20 SQS, 16 SNS — each asserting AWS-like behaviour (round-trips, attributes, deliveries),
  not just "the call returned". Raw logs: `tools/emulator-bakeoff/m44-results/<engine>.txt`.
- **Contract tests** (`services/api/tests/test_vpc.py`, `test_sqs.py`, `test_sns.py`): one real-sandbox
  test per service × engine through the runner, plus fast tests that pin the declared capability sets.
- **No egress is ever used**: SNS delivery is tested into an SQS queue inside the same sandbox.

Reproduce:

```bash
bash tools/emulator-bakeoff/m44_bakeoff.sh        # probes on all engines, writes m44-results/*.txt
scripts/test-api.sh tests/test_vpc.py tests/test_sqs.py tests/test_sns.py   # real sandboxes
```

## Result summary

| | Moto 5.2.3 | Floci 2.1.0 | MiniStack 1.5.16 |
|---|---|---|---|
| VPC (32 checks) | **32 / 32** | **32 / 32** | **32 / 32** |
| SQS (20 checks) | **20 / 20** | **20 / 20** | **20 / 20** |
| SNS (16 checks) | **16 / 16** | **16 / 16** | **16 / 16** |
| Memory during the run | 192 MiB | 40 MiB | 59 MiB |
| Sandbox start under hardening | healthy | healthy | healthy |
| Wider VPC surface (NAT / peering / endpoint / flow logs) | NAT, peering, endpoint ✔ · flow logs ✘ | all ✔ (config records) | all ✔ |
| SNS topic tags | full | read-only (writes fail) | writes work, `CreateTopic` tags ignored |

The VPC service rides the **EC2 API**; the probe and contract tests use the `ec2` client through the
CloudLabs service name `vpc` (see "Capability layer" below).

## VPC findings (EC2 API)

Verified on **all three engines** (12 checks in the probe, 28 operations in the contract): `CreateVpc`,
`DescribeVpcs`, `DeleteVpc`, `ModifyVpcAttribute`, `DescribeVpcAttribute`, `CreateSubnet`,
`DescribeSubnets`, `DeleteSubnet`, `ModifySubnetAttribute`, `CreateRouteTable`, `DescribeRouteTables`,
`DeleteRouteTable`, `CreateRoute`, `DeleteRoute`, `AssociateRouteTable`, `DisassociateRouteTable`,
`CreateInternetGateway`, `DescribeInternetGateways`, `AttachInternetGateway`, `DetachInternetGateway`,
`DeleteInternetGateway`, `CreateSecurityGroup`, `DescribeSecurityGroups`,
`AuthorizeSecurityGroupIngress`, `RevokeSecurityGroupIngress`, `AuthorizeSecurityGroupEgress`,
`RevokeSecurityGroupEgress`, `DeleteSecurityGroup`.

Engine notes:

- **Floci** and **MiniStack** store routes, associations and internet-gateway attachments correctly
  (describe round-trips), so a "public subnet" is a real, gradeable configuration.
- **Floci** does *not* refuse `DeleteVpc` while a subnet exists — it **cascades** (AWS raises
  `DependencyViolation`). Grading must not depend on dependency errors; a break-fix lab about
  dependency errors should pin Moto. Floci's startup log also shows it trying to reconcile Docker
  networks for VPCs (`unix://localhost:2375`) and degrading to configuration-only records, which is
  expected without a Docker socket.
- **Moto** is AWS-faithful on dependency refusal and is the only engine without flow logs (not needed
  for the core scope).
- **Elastic IPs, NAT gateways, peering and endpoints exist on some engines but are not part of the M44
  teaching scope** and are declared `unsupported` (they are configuration records anyway — there is no
  data plane in a no-egress sandbox).

## SQS findings

Verified on **all three engines** (20 checks; 16 contract operations): `CreateQueue` (including
attributes and FIFO `*.fifo` queues), `GetQueueUrl`, `ListQueues`, `GetQueueAttributes`,
`SetQueueAttributes`, `DeleteQueue`, `SendMessage` (body + message attributes round-trip),
`ReceiveMessage`, `ChangeMessageVisibility`, `DeleteMessage`, `SendMessageBatch`, `DeleteMessageBatch`,
`PurgeQueue`, `TagQueue`, `ListQueueTags`, `UntagQueue`.

Engine notes:

- Message bodies, message attributes and the standard queue attributes (`VisibilityTimeout`,
  `MessageRetentionPeriod`, `ReceiveMessageWaitTimeSeconds`, `ApproximateNumberOfMessages`) round-trip
  identically on all three. FIFO ordering held for a two-message probe.
- `AddPermission` is implemented on all three but meaningless with fixed sandbox credentials; declared
  `unsupported` (no access-control labs).
- Queue delete is immediate (no 60 s re-use window in the emulators).

## SNS findings

Verified on **all three engines** (16 checks; 12 contract operations): `CreateTopic`, `ListTopics`,
`GetTopicAttributes`, `SetTopicAttributes`, `DeleteTopic`, `Subscribe` (SQS endpoint; HTTP subscription
management), `ListSubscriptionsByTopic`, `GetSubscriptionAttributes`, `SetSubscriptionAttributes`
(`RawMessageDelivery`), `Unsubscribe`, `Publish`, `PublishBatch`.

Delivery was tested end-to-end: `Publish` → subscribed SQS queue, both **enveloped** (JSON
`Type: Notification`) and **raw** (`RawMessageDelivery=true`), plus `PublishBatch` (2/2 delivered) and
`Publish` after delete correctly refused.

Engine notes:

- **Floci**: `TagResource`/`UntagResource` fail at the protocol level (botocore cannot parse the
  response — `KeyError: TagResourceResult`); tags passed to `CreateTopic` *are* readable.
  An HTTP subscription is accepted but its `SubscriptionConfirmation` cannot be sent (no egress) —
  expected, management-only.
- **MiniStack**: `CreateTopic` ignores its `Tags` argument; `TagResource`/`UntagResource` themselves
  work.
- Topic tags are therefore out of the M44 teaching scope (`unsupported`), documented per engine.

## Capability layer changes

Kept behind the existing abstraction; no engine names leak:

- `app/runtime/capabilities/{moto,floci,ministack}.yaml` now declare `vpc` (28 supported + 5
  unsupported), `sqs` (16 + 1) and `sns` (12 + 3), with per-engine notes. Declared sets are **identical
  across all three engines**, enforced by fast tests.
- `app/runtime/emulators.py`: `SERVICE_CLIENT = {"vpc": "ec2"}` maps the CloudLabs service name to the
  boto3 client; nothing else branches on the engine.
- **`CONSOLE_OPS` is unchanged** (no entries for `vpc`, `sqs`, `sns`), and `service_status()` only reports
  services that have a console page, so the student catalogue is exactly the five current services and no
  UI or API announcement happens by accident. The entry is added with the console page, not before.

## Recommended default engine per service (no switch in this session)

| Service | Recommended default | Why | Fallback |
|---|---|---|---|
| VPC | **Floci** (already the platform default) | 32/32, ~5× less memory than Moto, routes/IGW/associations correct | Moto — prefer when a lab teaches `DependencyViolation` |
| SQS | **Floci** | 20/20, lowest footprint | Moto |
| SNS | **Floci** | 16/16 including raw and batch delivery | Moto |

- No configuration changes were made: `CL_DEFAULT_EMULATOR` stays `floci`, labs still use
  `runtime.emulator: default`.
- **MiniStack stays specialised** (only labs that pin it, e.g. Lambda code execution). It passes all
  three contracts (except the topic-tag quirk) and is the natural engine for a future
  "Lambda + SQS/SNS without Docker" lab, but not for the default path.
- Per-engine VPC/SQS/SNS parity tests exist so a future engine upgrade cannot silently break a service
  on one engine.

## Proposed deterministic grader checks (minimal)

Evidence stays a pure function of stored state (same convention as S3/DynamoDB/IAM/EC2). Proposed
collectors:

- `vpc` — describes VPCs, subnets, route tables (routes + associations), internet gateways
  (attachments) and security groups (rules), keyed by `Name` tags; no ids, ARNs or timestamps.
- `sqs` — queues by name with `VisibilityTimeout`, `MessageRetentionPeriod`, `DelaySeconds`,
  `ApproximateNumberOfMessages`, tags, and a **non-destructive peek** (`ReceiveMessage` with
  `VisibilityTimeout=0`, up to 10 messages; bodies only, sorted).
- `sns` — topics by name with `DisplayName` and subscriptions (`protocol`, endpoint queue name).

Minimal check set (each with the evidence it reads):

| Check | Params (example) | What it proves |
|---|---|---|
| `vpc.exists` | `name`, `cidr?` | the VPC was created with that CIDR |
| `vpc.subnet` | `name`, `cidr`, `vpc?`, `public?` | subnet in the VPC, optionally `MapPublicIpOnLaunch` |
| `vpc.route` | `route_table`, `destination`, `target` (`igw:<name>` / `local`) | route table routes to an internet gateway |
| `vpc.subnet_route_table` | `subnet`, `route_table` | the association was made (public-subnet pattern) |
| `vpc.internet_gateway_attached` | `name`, `vpc` | the IGW is attached to the VPC |
| `vpc.security_group_rule` | `group`, `direction`, `protocol`, `port`, `cidr`, `expect` | ingress/egress rule present/absent (mirrors `ec2.security_group_rule`) |
| `sqs.queue_exists` | `name`, `fifo?` | queue created (and is/ isn't FIFO) |
| `sqs.queue_attribute` | `queue`, `attribute`, `value` | e.g. visibility timeout / retention set correctly |
| `sqs.queue_tag` | `queue`, `key`, `value` | tagging exercise |
| `sqs.message_present` *(probe)* | `queue`, `body_contains?` | the student's message is actually in the queue |
| `sns.topic_exists` | `name`, `display_name?` | topic created |
| `sns.subscription` | `topic`, `protocol: sqs`, `endpoint` (queue name), `expect` | queue subscribed to the topic |
| `sns.publish_delivered` *(probe)* | `topic`, `queue`, `marker` | a publish reaches the queue (raw or enveloped) |

Notes:
- Probes follow the `lambda.invoke_returns` pattern: they run **during evidence capture**, and only their
  result is stored; grading is still pure. `sqs.message_present` restores visibility (`0 s`) so the
  student's queue is unchanged; `sns.publish_delivered` uses a unique marker and deletes only its own
  message.
- Ordering is best-effort in SQS; checks look for a matching body among the first N messages rather than
  asserting a position.
- No check depends on `DependencyViolation`, error strings, queue URLs, ARNs or resource ids.

## Proposed FastAPI endpoint shape

Same conventions as the existing consoles (`/api/sessions/{session_id}/console/<service>/…`, ownership
404, 409 when the session is frozen, pydantic bodies, `X-CSRF-Token` on mutations):

**VPC** — `console/vpc` (ec2 client under the hood):

```
GET    /console/vpc/overview                       # vpcs + subnets + route tables + igws + sgs (one page load)
POST   /console/vpc/vpcs                           # {name, cidr}
POST   /console/vpc/vpcs/{vpc_id}/delete
POST   /console/vpc/subnets                        # {vpc_id, name, cidr, az, public}
POST   /console/vpc/subnets/{subnet_id}/delete
POST   /console/vpc/route-tables                   # {vpc_id, name}
POST   /console/vpc/route-tables/{id}/routes       # {destination_cidr, target: "igw:<id>" | "local"}
POST   /console/vpc/route-tables/{id}/associate    # {subnet_id}
POST   /console/vpc/route-tables/{id}/disassociate # {association_id}
POST   /console/vpc/route-tables/{id}/delete
POST   /console/vpc/internet-gateways              # {name}
POST   /console/vpc/internet-gateways/{id}/attach  # {vpc_id}
POST   /console/vpc/internet-gateways/{id}/detach
POST   /console/vpc/internet-gateways/{id}/delete
POST   /console/vpc/security-groups                # {vpc_id, name, description}
PUT    /console/vpc/security-groups/{id}/rules     # inbound+outbound lists (like ec2)
DELETE /console/vpc/security-groups/{id}
```

**SQS** — `console/sqs`:

```
GET    /console/sqs/queues                         # name, fifo, visibility timeout, deeper counts
POST   /console/sqs/queues                         # {name, fifo, visibility_timeout, retention_period}
GET    /console/sqs/queues/{name}                  # attributes + tags + counts
PUT    /console/sqs/queues/{name}/attributes
POST   /console/sqs/queues/{name}/messages         # {body, attributes[]}            → send
POST   /console/sqs/queues/{name}/peek             # receive up to 10, VisibilityTimeout=0 (no state change)
POST   /console/sqs/queues/{name}/messages/delete  # {receipt_handle}
POST   /console/sqs/queues/{name}/purge
DELETE /console/sqs/queues/{name}
```

**SNS** — `console/sns` (resources addressed by topic/queue *name*, ARNs only in responses):

```
GET    /console/sns/topics
POST   /console/sns/topics                         # {name, display_name}
GET    /console/sns/topics/{name}                  # attributes + subscriptions
PUT    /console/sns/topics/{name}/attributes
DELETE /console/sns/topics/{name}
POST   /console/sns/topics/{name}/subscriptions    # {protocol: "sqs", queue}   (http management only later)
POST   /console/sns/topics/{name}/subscriptions/delete   # {subscription_arn}
POST   /console/sns/topics/{name}/publish          # {subject, message}         (delivery: sqs only)
```

`CONSOLE_OPS` for each service is added with its console page (all `supported` ops the page calls), so
`GET /console/services` only advertises a page once it is complete.

## Proposed student-console information architecture

- **Nav**: three new entries — **VPC**, **SQS**, **SNS** — next to S3/DynamoDB/IAM/EC2/Lambda, shown
  through the existing capability filter (no engine names, unavailable pages labelled).
- **VPC**: "Your VPCs" list (default VPC marked), detail with tabs **Subnets · Route tables ·
  Internet gateways · Security groups**, and a small public-subnet explainer. Creation dialogs follow
  AWS vocabulary (CIDR, AZ, route target). Reuse the security-group rule editor from EC2.
- **SQS**: queue list ("Standard"/"FIFO" badge, message count), detail with **Send message**,
  **Messages** (peek with visibility-timeout semantics), **Attributes**, **Tags**; delete confirms.
- **SNS**: topic list, detail with **Attributes**, **Subscriptions** (pick an in-sandbox SQS queue) and
  **Publish**; a clear "delivery only to queues inside your sandbox" note (no egress). No email/SMS.
- Cross-service hint (later): a lab briefing can link VPC → EC2 (launch into a subnet) and SNS → SQS,
  consistent with the existing lab-player console tabs.

## Tests and evidence

- `tests/test_vpc.py`, `tests/test_sqs.py`, `tests/test_sns.py`: **13 passed** (4 fast parity/mapping
  tests + 9 real-sandbox contract tests on Moto, Floci and MiniStack through the runner).
- VPC implementation: `tests/test_vpc_console.py` (pure grading, console journey, rules editing,
  break-fix state, break-action compiler) plus labtest in `tests/test_vpc.py`
  (`vpc-basics` 0/50/100 and `vpc-breakfix` 25/65/100 + Reset on **moto and floci**); E2E
  `apps/web/e2e/vpc.spec.ts` **2/2** on the compose stack.
- SQS implementation: `tests/test_sqs_console.py` (pure grading including the peek probe, console journey,
  the attributes incident) plus labtest in `tests/test_sqs.py` (`sqs-basics` 0/35/100 and `sqs-breakfix`
  20/70/100 + Reset on **moto and floci**); E2E `apps/web/e2e/sqs.spec.ts` **2/2**.
- `tools/emulator-bakeoff/m44-results/{moto,floci,ministack}.txt` + `versions.txt` hold the raw probe
  evidence (68 result rows per engine, container health, memory, emulator errors).
- Re-run `m44_bakeoff.sh` and the three contract files on every emulator version bump, as with the
  original bake-off.

## Deliberately not done (and open items)

- SNS is still a proposal: no console page, no `CONSOLE_OPS` entry, no lab packs/templates, no grader
  checks or evidence collector yet (VPC and SQS are implemented — see the top of this file).
- No production default change and no `lab.yaml` schema change beyond adding `vpc` and `sqs` to the
  service list.
- Open: implement `sns` collectors + checks and the console page in the same shape; a
  **Lambda + SQS + DynamoDB** template (MiniStack, in-process) and a **VPC + EC2** template (Floci);
  decide whether any lab needs Moto pinned for `DependencyViolation`.
