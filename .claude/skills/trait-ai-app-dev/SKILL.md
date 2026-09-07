---
name: trait-ai-app-dev
description: Run, rebuild, test, and troubleshoot the TRAIT-AI-APP stack (postgres, redis, ldap, ollama, backend, worker, frontend) — the concrete Docker Compose commands and the real gotchas already hit while building this project, not a generic Docker tutorial.
---

# Running TRAIT-AI-APP

This is the real implementation of the TRAIT-AI design (sibling `TRAIT-AI/`
folder — a Claude Design mockup, **never modified** by this project).
Everything below assumes the working directory is `TRAIT-AI-APP/`.

## Everyday commands

```bash
docker compose up -d          # postgres + redis + ldap + ollama + backend + worker + frontend
docker compose ps             # confirm everyone is healthy
docker compose logs -f worker # watch the Celery task / real OCR calls
make test                     # backend pytest, inside Docker, own test DB — run it TWICE, it must be stable both times
make test-front                # frontend vitest
make typecheck-front           # tsc -b
make lint                      # ruff
```

Login for manual testing: http://localhost:5173, `h.mansouri` / `secret123`
(or `a.trabelsi` / `secret123`) — real users seeded into the bundled `ldap`
service, real LDAP bind + JWT, not a stub.

## After any code change that needs a rebuild

Editing `back/`/`front/` source hot-reloads automatically (bind-mounted,
`--reload`/Vite dev server). But `requirements.txt`, `package.json`, or a
`Dockerfile` change needs an explicit rebuild — the running containers
don't pick it up on their own:

```bash
docker compose build backend worker      # or: frontend
docker compose up -d                     # recreate with the new image
```

## Database migrations — dev vs test are two different databases

`make test` auto-migrates the **test** database (`trait_ai_test`) every
run via a session-scoped pytest fixture. It does **not** touch the **dev**
database (`trait_ai`) the running app actually uses. After adding a new
Alembic migration, always also run:

```bash
docker compose run --rm backend alembic upgrade head
```

Forgetting this is a real mistake made in this project (Sprint 9): the
code was correct, tests were green, but the live app hit
`psycopg.errors.UndefinedTable` because the new table only existed in the
test DB. If a live/manual check throws an "UndefinedTable"/"UndefinedColumn"
error right after adding a migration, this is almost certainly why.

## Known port conflicts on this machine

Other unrelated local projects on this host sometimes already bind
`8000` (a `gpt-researcher` container) or `6379` (Redis). Never touch
someone else's container to free a port — remap this project's own port in
`.env` instead (see `.env.example`'s comments):

```
BACKEND_PORT=8001   # frontend's VITE_API_BASE_URL follows this automatically
REDIS_PORT=6380     # already the checked-in default for exactly this reason
```

If `docker compose up -d` fails with `port is already allocated`, check
`docker ps` for what's actually holding it before assuming this project's
compose file is broken.

## Editing `docker-compose.yml`, `back/Dockerfile`, or `front/Dockerfile`

Both Dockerfiles are **multi-stage** (`dev` / `production`, `front/` adds
an intermediate `build` stage). `docker-compose.yml`'s `backend`/`worker`/
`frontend` services pin `target: dev` explicitly — if that ever gets
removed, `docker compose build` silently picks the *last* stage
(`production`: no `--reload`, no dev deps) and local dev breaks in a
confusing way. Keep `target: dev` on every service build in the dev
compose file.

For the **production** composition (`docker-compose.prod.yml`,
`.env.prod.example`), see README.md's "Production deployment" section —
it has no default secrets by design and refuses to start without them.

## Windows-specific gotcha: Vite serving stale code

If you edit frontend source and the running app in the browser doesn't
reflect it (even after a hard refresh), it's very likely this: file-change
events from the Windows-host bind mount don't reach chokidar's default
watcher inside the Linux container. `front/vite.config.ts` already sets
`server.watch.usePolling = true` to fix this — if it's ever removed and
this bites again, that's the fix. As a one-off unblock,
`docker compose restart frontend` also forces a fresh read.

## Live-validate in a real browser, not just `curl`

`curl` never enforces CORS, browser-only auth headers, or React effect
timing. This project's own history has three real bugs that only a real
browser (Playwright, `chromium.launch()` — no `chromium-cli` on this
Windows host, so drive it directly with a small throwaway Node script in
the scratchpad) ever caught: a missing CORS config (Sprint 5), a session
lost on page reload from a `useEffect` ordering race (Sprint 7), and a
`<img>` tag silently failing to carry an Authorization header (Sprint 7).
Before calling a frontend-touching change "done," run it through an actual
browser end to end (login → the feature → check `console` for errors), not
just the automated test suite.

See `BACKLOG.md` for the full sprint-by-sprint history of what was built,
what broke, and how it was found and fixed — it's the definitive account
of this project's real gotchas, not this file's summary of them.
