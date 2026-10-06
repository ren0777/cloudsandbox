# Isolated checkouts (development only)

Overrides that let a second or third checkout (a git worktree) run its own copy of the stack next to the
default one: its own Compose project name, host ports, runner ids, sandbox env label and image tags, so
containers, networks, volumes, runners and the test database are never shared (STATUS D47, D53).

Always pass the base file first, so relative paths resolve from `infra/`:

```sh
docker compose -p cloudlabs-m45 -f infra/docker-compose.yml -f infra/dev-isolation/docker-compose.m45.yml \
  --profile multi up -d --build
CL_COMPOSE_PROJECT=cloudlabs-m45 CL_COMPOSE_EXTRA_FILE=infra/dev-isolation/docker-compose.m45.yml ./scripts/test-api.sh
```

Rules for a new override (each one was learned the hard way):
- set the `cloudlabs.env` **label** on `api` explicitly, not only `CL_ENV` (D53b);
- keep `http://localhost:3000` in `CL_ALLOWED_ORIGINS` (D53c);
- give `api` and `api-test` **different image tags** (they build the `runtime` and `test` stages);
- runner secrets must pass the startup check: at least 32 characters, no `change-me` (D55).

The secrets here are development values for a local machine, never for a deployment.
