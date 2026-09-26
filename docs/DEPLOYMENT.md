# Deploying CloudLabs

Two supported shapes:

| Shape | When | Servers |
|---|---|---|
| **One server** | a department pilot, up to ≈15 concurrent labs on a 32 GB / 8-core machine | control plane + one runner on the same host (`direct` access mode) |
| **Multi-runner** | whole classes at once | one control-plane server + N runner servers (`gateway` access mode) |

Everything runs in Docker. The control plane is `postgres`, `api`, `web` and `gateway` (nginx). A runner is one
container holding the host's Docker socket, which creates each student's sandbox (emulator + terminal on a
private, internal network). The API never talks to Docker; it talks to runners over HMAC-signed HTTP
(`docs/SECURITY.md`).

```
           Internet ──443──▶ gateway (TLS) ──▶ web, api ──▶ Postgres
                                                  │  signed runner API (7070, private network only)
                    ┌─────────────────────────────┼───────────────────────────┐
              runner (control-plane host)   runner-lab2 (gateway)      runner-lab3 (gateway)
                 └ sandboxes                   └ sandboxes                 └ sandboxes
```

---

## 1. Prepare every Docker host

1. Install Docker Engine 24+ (Linux) with the Compose plugin. Enable it at boot.
2. **Address pools (required above ≈25 sandboxes per host).** Every sandbox is its own bridge network. With
   Docker's default pools a host runs out after about 30 networks ("could not find an available, non-overlapping
   IPv4 address pool"). Give Docker a large pool of small subnets in `/etc/docker/daemon.json`, then
   `systemctl restart docker`:
   ```json
   { "default-address-pools": [ { "base": "10.200.0.0/16", "size": 28 } ],
     "log-driver": "local", "log-opts": { "max-size": "20m", "max-file": "3" } }
   ```
   `/28` gives 4,096 sandbox networks. Choose a `base` that doesn't overlap your campus network.
3. Build the sandbox images once per version on every host that runs sandboxes (runner hosts), or build on one
   machine and move them: `docker save cloudlabs/emulator-floci:v1 cloudlabs/terminal:v1 … | ssh host docker load`.

## 2. One server

```bash
git clone … cloudlabs && cd cloudlabs
cp infra/production/production.env.example production.env && chmod 600 production.env
#   fill in every secret (openssl rand -base64 36), PUBLIC_HOST and TLS_DIR
docker compose -f infra/docker-compose.yml --profile images build            # sandbox images
docker compose -f infra/docker-compose.yml -f infra/production/docker-compose.prod.yml \
               --env-file production.env up -d --build
```

`infra/production/docker-compose.prod.yml` switches the laptop stack to production:

| | Laptop stack | Production override |
|---|---|---|
| Demo accounts | on (`CL_DEMO_MODE=true`) | **off** (refused at login) |
| Secrets | development defaults | from `production.env` |
| Postgres | published on 127.0.0.1:55432, fixed passwords | **not published**; role passwords set from secrets by `init-roles.sh` on first start |
| Gateway | http :3000 | **TLS** on 443, :80 redirects (config `infra/production/nginx-tls.conf`) |
| Runner | 4 seats | `RUNNER_MAX_SANDBOXES` (default 8) |

Create the first admin (demo accounts are disabled):
```bash
docker compose … exec api python -c "
import asyncio; from app.db import sessionmaker; from app.auth.routes import create_user; from app.models import Role
async def main():
    async with sessionmaker()() as db:
        await create_user(db, 'you@college.edu', 'Your Name', Role.admin, 'a-temporary-password', must_change_password=True); await db.commit()
asyncio.run(main())"
```
Sign in, change the password, then create instructor accounts under **Users** and courses under **Courses & staff**.

## 3. Add a runner server (multi-runner)

On the new server (Docker prepared as in §1):
```bash
cd cloudlabs/infra/runner-host
cp runner.env.example runner.env && chmod 600 runner.env
#   RUNNER_ID=runner-lab2, a new random RUNNER_SECRET, RUNNER_PUBLIC_URL=http://<private-ip>:7070, PRIVATE_IP
docker compose --env-file runner.env --profile images build     # or docker load the images
docker compose --env-file runner.env up -d
```
The runner starts in **gateway** mode: it attaches itself to each sandbox network and forwards only that
sandbox's emulator and terminal traffic at `/gw/<sandbox>/<token>/…`. The API server never joins the runner
host's Docker networks.

Register it from the control-plane server, either in **Runtime → Register runner** (id, URL, secret) or with:
```bash
docker compose … exec -e RUNNER_SECRET='<its secret>' api python -m app.runtime.fleet register runner-lab2 http://10.0.0.12:7070
```
Registration calls the runner's signed capacity endpoint and refuses to save it unless the runner answers with the
same id. The secret is stored encrypted. Within 15 s the Runtime page shows the runner's health, engine images, CPU
and memory, and the scheduler starts placing new labs on it.

**Scheduling.** A new lab goes to a runner that is healthy (heartbeat within 90 s), not draining, has the lab's
engine and terminal images, and has a free seat. Among those, the least-loaded runner wins. A running lab never
moves to another runner.

## 4. TLS

- Terminate TLS at the gateway (`infra/production/nginx-tls.conf`). Mount `fullchain.pem` and `privkey.pem`
  from `TLS_DIR`. For Let's Encrypt, point certbot's webroot at `ACME_DIR`
  (`certbot certonly --webroot -w /var/www/acme -d labs.college.edu`) and reload nginx after renewal
  (`docker compose … exec gateway nginx -s reload`).
- The API sets cookies `Secure`, `HttpOnly` and `SameSite=Lax`, and only accepts WebSocket origins listed in
  `CL_ALLOWED_ORIGINS` (set from `PUBLIC_HOST`). The site must be served over HTTPS.
- **Runner links** carry HMAC-signed requests (timestamped, replay window 30 s) and per-sandbox gateway tokens.
  They are designed for a **private network**. Across untrusted networks, put runner traffic inside a
  WireGuard/IPsec tunnel between the servers. Native mTLS between API and runners (PLAN §10) isn't implemented
  yet; the tunnel gives the same confidentiality today.

## 5. Secrets

| Secret | Where | Notes |
|---|---|---|
| `CL_SECRET_KEY` | control plane | Signs sign-in tokens **and** encrypts stored runner secrets and terminal credentials. Rotating it signs everyone out, and you must re-register every runner (Runtime → Register runner again with its secret). |
| `CL_RUNNER_SECRET` | control plane + its local runner | HMAC key of the platform's own runner. |
| `RUNNER_SECRET` (per runner) | runner server + registered once in the control plane | Different for every runner. Rotate: set a new value on the runner, restart it, register again. |
| `POSTGRES_SUPERUSER_PASSWORD`, `CLOUDLABS_OWNER_PASSWORD`, `CLOUDLABS_APP_PASSWORD` | control plane | The API serves requests as `cloudlabs_app`, which has no UPDATE/DELETE on grades, evidence or audit. `cloudlabs_owner` runs migrations only. |

Keep `production.env` and `runner.env` out of git (mode 600, owned by root). Back them up separately from the database.

## 6. Firewall and networking

| From → To | Port | Allow |
|---|---|---|
| Internet → control plane | 443 (and 80 for redirects/ACME) | yes |
| Control plane → each runner | 7070/tcp | **only** from the control-plane server's private IP |
| Runner → control plane | none | runners never initiate connections to the API |
| Anything → Postgres | 5432 | **no** (not published; internal Docker network only) |
| Sandboxes → anywhere | — | none: sandbox networks are `internal` (no route out), verified by tests |
| Runner hosts → Internet | 443 | only while pulling or building images |

Never expose the Docker socket or port 7070 publicly. The runner's `/v1/*` API is HMAC-authenticated, and
`/gw/*` answers only with a valid per-sandbox token, but both assume a private network.

## 7. Backups (Postgres)

Everything that matters (accounts, courses, lab versions, attempts, grades, **immutable evidence**, audit log)
is in Postgres. Sandboxes are ephemeral by design and aren't backed up.

**Back up nightly** (and before every upgrade), as the owner role, in custom format:
```bash
docker compose … exec -T postgres sh -c \
  'PGPASSWORD="$CLOUDLABS_OWNER_PASSWORD" pg_dump -h localhost -U cloudlabs_owner -d cloudlabs -Fc' \
  > backups/cloudlabs-$(date +%F).dump
```
Keep at least 14 daily and 8 weekly copies off the server. Evidence and audit rows are append-only in the
database, so the backups are also your tamper-evident history.

**Restore** (tested procedure, see `docs/STATUS.md` R4): stop `api`, then:
```bash
docker compose … stop api
docker compose … exec -T postgres psql -U postgres -c "DROP DATABASE cloudlabs" -c "CREATE DATABASE cloudlabs OWNER cloudlabs_owner"
docker compose … exec -T postgres psql -U postgres -d cloudlabs \
  -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC" -c "ALTER SCHEMA public OWNER TO cloudlabs_owner" -c "GRANT USAGE ON SCHEMA public TO cloudlabs_app"
docker compose … exec -T postgres sh -c \
  'PGPASSWORD="$CLOUDLABS_OWNER_PASSWORD" pg_restore -h localhost -U cloudlabs_owner -d cloudlabs --exit-on-error' < backups/cloudlabs-YYYY-MM-DD.dump
docker compose … start api
```
The dump restores the tables, the append-only triggers and the app role's grants. After restoring, sessions that
were running at backup time have no sandbox. The reconciler marks them `sandbox_lost` (no attempt used) within
30 s, and students simply start again. Verify with **Runtime** and a test sign-in.

## 8. Upgrades

1. Read the release notes and take a **backup** (§7).
2. **Drain every runner** that will restart (Runtime → Drain, or `python -m app.runtime.fleet drain <id>`). New labs
   stop being placed there, and running labs finish normally. Wait until the runner shows **Drained: safe to stop**.
   For a runner-less window, do it outside class hours; students who press Start see "all lab seats are in use"
   and retry automatically.
3. Build or pull the new images with a new `CLOUDLABS_VERSION` tag (keep the old tag for rollback).
4. Control plane: `docker compose … up -d --build`. The API runs database migrations on start (`app.migrate`,
   as the owner role). Watch `docker compose logs api` for "Application startup complete".
5. Runners: on each runner server `docker compose --env-file runner.env up -d`, then **Resume** it in Runtime.
6. Smoke test: Runtime shows every runner healthy with its engines, and one lab start → submit works.

Recreating the API or a runner container **while labs are running** is safe (sessions reattach), but draining
first avoids interrupting students. If a runner reports "empty sandbox network(s) Docker could not remove",
restart Docker on that host during the next drain (a Docker engine quirk with stale endpoints; it holds no student
resources and doesn't take a seat).

## 9. Rollback

- **Application only** (no migration in the release): redeploy the previous `CLOUDLABS_VERSION` tag. Done.
- **With migrations:** drain, stop `api`, restore the pre-upgrade backup (§7), deploy the previous tag, resume.
  Alembic `downgrade` scripts exist for every migration, but **restoring the backup is the supported rollback**:
  append-only data written by the new version would otherwise have to be discarded by hand.
- Never downgrade the database while a newer API version is running.

## 10. Operating

- **Runtime page:** runner health, seats in use, host memory, engine images, provisioning p50/p95, failures in the
  last 24 h, and every running lab with +15 min / End.
- **Metrics:** `/metrics` (Prometheus) on the internal network. Alert on `session_failures_total`,
  `capacity_rejections_total` and runner health.
- **A runner goes down:** new labs go elsewhere immediately. Its labs stay as they are for 5 minutes
  (`CL_RUNNER_LOST_AFTER_S`) in case it comes back. After that they end as `runner_lost` (no attempt used) and are
  never moved to another server. When it returns, leftover sandboxes are removed automatically.
- **Sizing:** see `docs/LOADTEST.md`. Floci sandboxes use about 30–40 MiB of RAM each when idle, but provisioning
  and grading are CPU-bound. Plan about 0.5 CPU per concurrent lab, and run `python -m app.loadtest` on your
  hardware before setting `RUNNER_MAX_SANDBOXES`.
