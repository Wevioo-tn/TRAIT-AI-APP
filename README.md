# TRAIT-AI — Contrôle des instruments de paiement

Real implementation of the TRAIT-AI design (see the sibling `TRAIT-AI/`
folder, which is a Claude Design mockup and is **never modified** by this
project). This app is being built in validated phases: each phase ships
with automated tests, and the next phase only starts once the current one
is reviewed and approved.

Continuing this project with Claude Code? Three project skills under
`.claude/skills/` capture the operational know-how so it doesn't need
rediscovering: `trait-ai-app-dev` (running/rebuilding/troubleshooting the
stack), `trait-ai-app-ocr-providers` (switching and validating the real
OCR backends), and `trait-ai-app-sprint-workflow` (the validation
discipline and `BACKLOG.md` conventions this project has followed).

## Architecture

| Layer     | Choice                                    | Why |
|-----------|--------------------------------------------|-----|
| Frontend  | React + Vite + TypeScript                  | The mockup's own templating (`sc-if`/`sc-for`/component state) already mirrors React idioms; an SPA is enough since this is an internal, authenticated back-office tool (no SSR need). |
| Backend   | FastAPI + SQLAlchemy 2.0 + Alembic          | Pydantic models map directly onto the domain's validation rules (mentions obligatoires, RIB structure, date rules). Python also has the strongest OCR/NLP ecosystem, which the next phases depend on. |
| Database  | PostgreSQL                                  | Generated columns, native enums, JSONB for the audit log, schemas for logical separation. |
| Driver    | `psycopg` (v3)                              | One driver for both the async app engine and Alembic's sync engine — no asyncpg/psycopg2 split. |
| Async pipeline | Celery + Redis                         | The OCR/NLP analysis runs as a background job, not inline in a request — matches the design's own "processing" state instead of blocking the API on it. |

Everything runs in Docker. There is no supported "run it directly on the
host" path — `front/` and `back/` are each built and run as containers,
orchestrated by the root `docker-compose.yml`.

### OCR/extraction: a real VLM, chosen at deploy time, not baked into the code

The async pipeline (Celery, the state machine, the NLP fuzzy-matching
algorithm) is fully real and tested — and as of Sprint 8, so is extraction
itself, via a vision-capable LLM behind the same `Extractor` interface
`StubExtractor` (`app/services/extraction.py`) has always implemented:

```python
class Extractor(Protocol):
    def extract(self, traite: Traite, recto: bytes, verso: bytes) -> ExtractionResult: ...
```

`OCR_PROVIDER` in the environment picks the implementation
(`app/services/vlm_extraction.py`'s `get_extractor()`), because which
provider is allowed to see scanned bank instruments is a data-
residency/compliance decision, not a code change:

- `stub` (default) — `StubExtractor`, no real image reading at all. An
  unconfigured deployment must never silently start making real,
  possibly-billed external calls.
- `azure_openai` — Azure OpenAI's vision-capable chat model. The only real
  provider (per your call — a local/self-hosted option was evaluated and
  removed to keep this simple).

`VlmExtractor` sends the recto and verso as base64 images alongside a
prompt asking for both physical occurrences of each duplicated field
(this instrument type repeats numero_lcn/montant/dates/RIB/lieu for a
manual cross-check — see "Contrôle de cohérence des champs dupliqués"
below) plus the free-text tireur/tiré/ordre names used for NLP matching,
as strict JSON.

A real model can also just fail to follow the "respond only with JSON"
instruction — found live against a real (small, general-purpose) model
during this app's Sprint 8 evaluation, not hypothesized. `execute_analysis`
treats any extraction failure as an honest `ECARTS_A_TRAITER` outcome with
the real error recorded in the audit log (`analyse_echouee`), the same way
a low-confidence NLP match already does — never a traite stuck in
`EN_COURS_OCR` forever with no signal for a human to act on.

**What Sprint 8 proves and doesn't**: the plumbing — image bytes in,
structured fields out, PDF faces handled by honestly reporting absence
rather than crashing (vision chat APIs take images, not PDFs), extraction
failures resolved instead of hanging. It does **not** prove extraction
*accuracy* on a real bilingual FR/AR bank instrument — that needs an
actual accuracy pilot against real sample scans, tracked in BACKLOG.md,
deliberately kept separate from "does the architecture work."

### Raw extraction audit log — the one table that isn't SQLAlchemy

Every real VLM call (Sprint 9, per your call) also gets logged to
`extractions_ia` — provider, model, whether it succeeded, the **full raw
response text**, the error if any, and how long the call took. Unlike
every other table in this app, it's written and read through `psycopg`
directly (`app/services/extraction_log.py`), never the SQLAlchemy ORM, and
its own migration is hand-written raw SQL to match
(`migrations/versions/0004_extractions_ia_log.py`). It's also logged
through its own short-lived autocommit connection, independent of
`execute_analysis`'s SQLAlchemy transaction — the correct shape for an
audit log, since an entry must survive even when the business transaction
it's observing fails, and a failure to write it must never itself take
down the analysis pipeline (proven live, not just asserted — see
BACKLOG.md's Sprint 9 notes).

### Two databases, one Postgres instance

- `trait_ai` — the real/dev database.
- `trait_ai_test` — used exclusively by the automated test suite (created
  automatically on first startup by `back/db-init/01-create-test-db.sql`).
  Tests never touch `trait_ai`, so running the suite is always safe.

### The `imx` schema

`ADHERENTS` / `DEBITEURS` / `FACTURES` are the external IMX referential
system's tables (see the docs screenshots this schema was built from). In
production, the validated architecture decision is that this app connects
**read-only, directly to IMX's own database** — no API layer needed.
Locally, `imx.*` in this Postgres instance is a faithful stand-in with the
same shape, so the app can be built and tested end-to-end before that real
connection is wired up. Switching over later is a connection-string change
in `app/core/config.py`, not a data-model change — the ORM models
(`app/db/models/imx.py`) intentionally match IMX's real column names.

### Frontend

React + Vite + TypeScript, React Query for server state, React Router for
navigation. `theme.ts` and `styles/global.css` are copied verbatim from the
validated TRAIT-AI mockup (colors, fonts, and the already-responsive
`tp-*` classes) — they exist so dozens of components don't repeat literal
hex strings, not to introduce any new visual choice.

Two things needed for the frontend that the design mockup never modeled
(it only ever demoed one already-existing traite):

- **Tireur/Tiré display names**: the queue table needs names, not just the
  `code_adherent`/`code_debiteur` FKs `TraiteRead` originally exposed. Added
  `tireur_nom`/`tire_nom` (resolved via new `Traite.adherent`/`.debiteur`
  relationships) and a `GET /api/traites/counts` endpoint the 5 status
  cards need, neither scoped in Sprint 1.
- **Intake form**: a small block (N° L-CN, montant, dates) in the upload
  card. This project's own architecture decision (see "Two databases"
  above and BACKLOG.md) is that these values are declared at intake — from
  a bordereau de remise — not discovered by OCR, so creating a traite
  needs somewhere to enter them before any file can be attached to it.

**Auth is real** (Sprint 7): `POST /api/auth/login` binds against a real
LDAP directory (`app/services/ldap_auth.py`, backed in dev/CI by the
`ldap` service — see below) and returns a JWT; `auth/AuthContext.tsx`
persists `{token, username}` to `localStorage`, attaches the token to
every request, and forces a logout on any `401` (including a token that
expired mid-session). Every `/api/traites/*` route requires this token.
Documents (`DocumentViewer` in `AnalysisPage`) can't be fetched as a plain
`<img src>`/`<a href>` any more since that can't carry an Authorization
header — they're fetched as an authenticated blob and rendered via
`URL.createObjectURL` instead.

**CORS**: `cors_allowed_origins` in the backend's settings, defaulting to
the dev frontend origin(s). This exists because of a real bug — see
BACKLOG.md's Sprint 5 notes — every `curl`-based validation in this
project up to this point would have missed a missing CORS config entirely,
since curl doesn't enforce it. Only a real browser check caught it.

## Quickstart

```bash
cp .env.example .env      # optional — every value already has a safe default
make build
make up                   # postgres + redis + ldap + backend (:8000) + worker + frontend (:5173)
```

In another terminal, once postgres is healthy:

```bash
make migrate               # alembic upgrade head
make seed                  # populate imx.* with example referential data
make test                  # full backend test suite (own DB, never touches dev data)
```

Then open:
- Frontend: http://localhost:5173 — log in with `h.mansouri` / `secret123`
  (or `a.trabelsi` / `secret123`), the two users seeded into the dev `ldap`
  container (see `docker-compose.yml`'s `ldap` service — real bind, not a
  mock).
- Backend health check: http://localhost:8000/api/health
- Backend interactive docs: http://localhost:8000/docs

By default, launching an analysis uses `StubExtractor` (`OCR_PROVIDER=stub`
— see above). To try real extraction, set `OCR_PROVIDER=azure_openai` and
the real tenant credentials in `.env` (`AZURE_OPENAI_*`) — see
`.env.example` — then restart the `worker` service.

## Project layout

```
TRAIT-AI-APP/
├── docker-compose.yml             # dev — bind mounts, --reload, default creds
├── docker-compose.prod.yml        # production — see "Production deployment" below
├── .env.prod.example
├── Makefile
├── BACKLOG.md                    # sprints, tasks, status — source of truth
├── back/
│   ├── app/
│   │   ├── main.py              # FastAPI app + router registration
│   │   ├── core/config.py       # settings, all sourced from env vars
│   │   ├── api/routes/traites.py # traites CRUD + upload + analyse + status (auth-protected)
│   │   ├── api/routes/auth.py   # POST /auth/login (LDAP bind → JWT)
│   │   ├── api/deps.py          # get_current_user — the Bearer-token dependency
│   │   ├── schemas/traite.py    # Pydantic request/response models
│   │   ├── worker.py            # Celery app instance
│   │   ├── tasks/traite_processing.py  # the Celery task (callable directly for tests)
│   │   ├── services/
│   │   │   ├── ldap_auth.py            # real LDAP bind (never reads/stores the password)
│   │   │   ├── jwt_auth.py              # HS256 token issue/verify
│   │   │   ├── audit.py                # audit_log write-through
│   │   │   ├── storage.py              # file storage abstraction (local volume)
│   │   │   ├── verification_rules.py   # bloque/reco — pure port of the mockup's business rules
│   │   │   ├── extraction.py           # Extractor interface + StubExtractor
│   │   │   ├── vlm_extraction.py       # real extraction — Azure OpenAI / local LLM, see note above
│   │   │   ├── extraction_log.py       # raw psycopg — extractions_ia audit log, not the ORM (Sprint 9)
│   │   │   ├── nombres.py              # real French number-to-words (montant en lettres)
│   │   │   ├── nlp_matching.py         # rapidfuzz-based fuzzy matching — fully real
│   │   │   ├── traite_processing.py    # orchestrates one analysis pass
│   │   │   └── mentions_rules.py       # mentions obligatoires / date rules / facture matching
│   │   └── db/
│   │       ├── base.py          # shared declarative Base
│   │       ├── session.py       # async engine/session for the running API
│   │       └── models/
│   │           ├── imx.py       # Adherent / Debiteur / Facture (IMX shape)
│   │           └── traite.py    # this app's own operational tables
│   ├── migrations/               # Alembic — see "Database" below
│   ├── scripts/seed.py           # example referential data
│   └── tests/                    # pytest — see "Testing" below
└── front/
    └── src/
        ├── App.tsx                # routes + providers (Query/Auth/Toast/Router)
        ├── theme.ts                # design tokens, copied verbatim from the mockup
        ├── styles/global.css       # base resets + responsive tp-* classes, ported verbatim
        ├── api/{client,types}.ts   # hand-typed fetch client mirroring the backend schemas
        ├── auth/AuthContext.tsx    # real login (LDAP → JWT), persisted session, forced logout on 401
        ├── layouts/AppLayout.tsx   # topbar + outlet shell for authenticated routes
        ├── components/             # Topbar, StatusBadge, ToastProvider, ProtectedRoute
        ├── lib/format.ts           # montant/date/SLA formatting — real, derived from real data
        └── pages/                  # LoginPage, QueuePage, AnalysisPage (document viewer + verdict/mentions/checks — no decision panel, see Sprint 9)
```

## Database

Four migrations so far:

1. `0001_extensions_and_schemas` — `pgcrypto` extension (for
   `gen_random_uuid()`) and the `imx` schema. Alembic autogenerate cannot
   create schemas/extensions on its own, so this one is hand-written.
2. `0002_create_all_tables` — every table, **autogenerated** from the
   SQLAlchemy models (`alembic revision --autogenerate`), then hand-adjusted
   to explicitly drop the Postgres ENUM types on downgrade (Alembic doesn't
   do this on its own, and without it a downgrade→upgrade cycle — exactly
   what the test suite does every run — fails the second time with "type
   already exists").
3. `0003_add_document_metadata` — `content_type`/`taille_octets` on
   `traite_documents`, needed for the upload endpoint (Sprint 2) to serve
   files back with the right `Content-Type`.
4. `0004_extractions_ia_log` — the `extractions_ia` audit table (Sprint 9),
   the one exception to "every table is a SQLAlchemy model": it's written
   as raw SQL (`op.execute`, not `op.create_table`) because it's never
   touched through the ORM at all — see `app/services/extraction_log.py`.

`migrations/env.py` sets `include_schemas=True` — without it, autogenerate
silently ignores the `imx` schema entirely and will propose *recreating*
`imx.*` (which already exists) on every future migration. Found the hard
way while generating migration 0003; if this ever gets removed, every
subsequent autogenerate will be wrong in the same way.

Table-to-design mapping — every table traces back to one screen/section of
the mockup:

| Table                       | Mockup section |
|------------------------------|----------------|
| `imx.adherents`               | "Table ADHERENTS (correspond au Tireur)" |
| `imx.debiteurs`                | "Table DEBITEURS (correspond au Tiré)" |
| `imx.factures`                 | "Table FACTURES (calcul de couverture)" — `montant_net` is a real **generated column** (`montant_ttc - montant_avoirs`), not app-computed |
| `traites`                      | The queue list / analysis screen header |
| `traite_documents`             | Recto/verso upload |
| `champs_extraits`              | "Contrôle de cohérence des champs dupliqués" |
| `rapprochements_nlp`           | "Rapprochement NLP au référentiel IMX" |
| `verifications_manuelles`      | "Vérifications manuelles obligatoires" |
| `decisions`                    | The cashier's final decision — API/table still live and tested, but no longer reachable from the UI (see Sprint 9) |
| `audit_log`                    | "Toute action est horodatée et tracée" |
| `extractions_ia`               | Not in the design (it predates real OCR) — the raw audit trail of every real VLM call, see below |

**Not** modeled as tables: "mentions obligatoires" and the date-rule checks.
Both are derived at read time from `champs_extraits` /
`verifications_manuelles` plus the linked `imx.factures` row — storing them
separately would duplicate facts that already live elsewhere.

### Seed data

`back/scripts/seed.py` is idempotent (safe to re-run) and inserts two
groups of rows into `imx.*` only — never into the app's own `traites`,
since those are meant to be created by the real upload → OCR → NLP
pipeline, not faked ahead of time:

1. The literal example rows from IMX's own table documentation
   (`ADH-0142` / `DEB-0087` / `FA-26-0117`), kept byte-for-byte faithful to
   the source.
2. A fuller set matching the entities already used throughout the TRAIT-AI
   design mockup (ADACTIM, LA MÉDITERRANÉENNE, STE TEXTIS, ...), so the NLP
   reconciliation work in the next phase has real data to match against
   from day one.

## Testing

`back/tests/` runs against `trait_ai_test`, never against dev data:

- `conftest.py` rebuilds the test schema from scratch every session
  (`alembic downgrade base` → `upgrade head`), then hands each test its own
  transaction that's always rolled back — tests can't leak state into each
  other or require manual cleanup.
- `test_migrations.py` — asserts the schema shape (tables, columns, FKs,
  unique constraints, the generated column) matches the design.
- `test_seed_data.py` — asserts the seed script is correct, faithful to the
  documentation example, referentially intact, and idempotent. Notably,
  `test_documentation_example_matches_screenshot` feeds the exact TTC/avoirs
  from the docs through the real Postgres-computed column and checks it
  lands on 8 117,504 — proving the schema, not just Python arithmetic.
- `test_health.py` — smoke-tests `/api/health`.
- `test_traites_api.py` — the Traites API: create (incl. auto-seeded
  verification slots, duplicate/validation rejection), get, list
  (filter/paginate/sort), audit log write-through.
- `test_document_upload.py` — upload/download: content-type and size
  validation, duplicate-face rejection and explicit replace, and that the
  file actually round-trips byte-for-byte.
- `clean_app_tables` (in `conftest.py`) truncates this app's own tables
  before each API test, since HTTP-driven tests can't share the
  transaction-rollback trick `db_session` uses. The `client` fixture also
  overrides file storage to a throwaway temp directory (via the same
  dependency-injection pattern as the DB session), so uploads during tests
  never touch the real uploads volume.
- `test_verification_rules.py` / `test_verification_and_decision_api.py` —
  every reachable branch of the blocking rule, plus the PATCH/decision
  endpoints end to end.
- `test_nombres.py` — French number-to-words, including the classic
  irregularities (70s/80s/90s, cent/mille/million (in)variability).
- `test_extraction.py` / `test_nlp_matching.py` — the two pure building
  blocks of the analysis pipeline, independent of the DB or Celery.
- `test_vlm_extraction.py` — the real (Sprint 8) extraction path: JSON
  response parsing (raw/fenced/prose-wrapped/unparseable), the full
  fields/parties mapping and the PDF-skip path against a dependency-
  injected fake client, and `OCR_PROVIDER` dispatch — never a real,
  billed Azure OpenAI call in the suite.
- `test_extraction_log.py` — the raw-`psycopg` audit log (Sprint 9)
  exercised against the **real** test database, not mocked (unlike
  `test_vlm_extraction.py`, which mocks this module at the boundary): a
  round-trip write/read, a failed attempt with its full raw response,
  chronological ordering, per-traite scoping, and the "never raises"
  guarantee proven against an actual foreign-key violation.
- `test_traite_processing.py` — `executer_analyse` exercised directly
  against the test DB (real files on disk, real seeded referential rows) —
  no Celery involved.
- `test_celery_task.py` — proves the task *wrapper* itself works (its own
  engine creation, the `SYNC_DATABASE_URL_OVERRIDE` env var, its commit) by
  calling it directly rather than via `.delay()` — no broker needed to test
  a task's logic, only to actually dispatch one.
- `test_analyse_endpoint.py` — `POST .../analyse` and `GET .../status`,
  with `.delay()` monkeypatched to a spy (proving the API's own validation
  and state transitions, not Redis connectivity — that's validated live,
  see BACKLOG.md's Sprint 4 notes).
- `test_mentions_rules.py` — pure unit tests for the mentions-obligatoires
  and date-rule logic; date-based tests use offsets from `date.today()`,
  not hardcoded absolute dates (a fixed date silently drifts into the past
  as real time passes — caught exactly that way while building this file).
- `test_analysis_readmodel_api.py` — the one true end-to-end integration
  test: real `executer_analyse` → real `GET /api/traites/{id}` → asserts
  the mentions/date-rules/matched-facture read-model the frontend actually
  consumes.
- `test_auth.py` — `POST /api/auth/login` against the real `ldap` container
  (valid credentials, wrong password, unknown user gets the *same* 401 as
  wrong password so the endpoint can't be used to enumerate usernames,
  empty credentials), plus that `/api/traites` rejects both a missing and
  an invalid Bearer token.

Frontend (`front/src/**/*.test.tsx`, Vitest + Testing Library,
`make test-front`): `LoginPage`, `Topbar`, `QueuePage`, and `AnalysisPage`
component tests with the API client mocked, plus pure unit tests for the
formatting utilities. "Responsive" isn't meaningfully testable under
jsdom (no layout engine) — that was validated live in a real browser
instead (see BACKLOG.md's Sprint 5/6 notes), not asserted here. The real
LDAP → JWT flow (including session persistence across a page reload, and
the authenticated document-blob viewer) is likewise only meaningfully
testable live — see BACKLOG.md's Sprint 7 notes for what that live pass
caught.

```bash
make test          # or: docker compose run --rm backend pytest -v
make lint          # ruff
```

## Production deployment

`docker-compose.yml` (the one `make up` uses) is dev-only: bind-mounted
source, `--reload`, dev/test dependencies in the image, default
credentials. `docker-compose.prod.yml` is the production composition —
built from the same `back/Dockerfile`/`front/Dockerfile`'s `production`
stage:

- **Backend/worker**: only `requirements.txt` installed (no
  pytest/ruff/httpx), no bind mount, runs as a non-root `app` user, no
  `--reload`.
- **Frontend**: Vite builds the static SPA, then `nginxinc/nginx-unprivileged`
  (non-root by construction) serves it and reverse-proxies `/api/*` to the
  backend (`front/nginx.conf`) — the browser only ever talks to one origin,
  so there's no CORS configuration to get right in production.
- **No default secrets**: every security-relevant variable
  (`JWT_SECRET`, `LDAP_USER_DN_TEMPLATE`, Postgres/LDAP admin credentials)
  is a required env var with no fallback — `docker compose` refuses to
  start without it, rather than silently running with a dev default in
  production.

```bash
cp .env.prod.example .env.prod   # fill in every value — see the file's own comments
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend alembic upgrade head
```

`postgres`/`redis`/`ldap` are included so this is runnable end-to-end as a
reference — a real deployment will very likely point `DATABASE_URL` and
`LDAP_URL`/`LDAP_USER_DN_TEMPLATE` at the organization's actual managed
database and existing corporate directory instead of these bundled
services, and put a TLS-terminating load balancer in front of the
`frontend` container rather than exposing its port directly.

Validated by actually building and running this composition (not just
reading it): `alembic upgrade head` against a fresh production database,
`/api/health` reachable *through* nginx's reverse proxy, and a full real
browser login (real LDAP bind → real JWT → queue page) — see BACKLOG.md's
Sprint 7 notes, including the measured image-size reduction (backend
422 MB → 373 MB, frontend 632 MB → 74 MB) and confirmation via
`docker exec ... id` that both containers actually run as non-root.

## Roadmap

Tracked as a proper backlog in **[BACKLOG.md](BACKLOG.md)** — sprints,
tasks, and status live there now rather than here, so there's a single
source of truth. Short version: the DB foundations, the Traites API,
document upload, the verification/decision workflow, the OCR/NLP pipeline
with real VLM-based extraction (Azure OpenAI or a local model, switchable —
see above), the full frontend port, real LDAP/JWT auth, and production
Docker hardening are all done. What's deliberately not done: a real
extraction *accuracy* pilot against actual bilingual FR/AR scans — see
BACKLOG.md's Sprint 8 notes and "Backlog (not yet scheduled)" section.
