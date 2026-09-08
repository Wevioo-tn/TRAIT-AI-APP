# TRAIT-AI — Product Backlog & Sprint Plan

Owner: Scrum Master (this session). Source of truth for where the project
stands — checkboxes are updated as sprints complete. Each sprint ends with
its own test suite green before the next one starts (same validated-phase
discipline as the Phase 1 foundations already shipped).

## Working agreement

- One sprint = one coherent, independently testable slice of the system.
- A sprint is not "done" until: code written, automated tests written and
  passing (inside Docker), and a summary posted here for review before the
  next sprint starts.
- Nothing in `TRAIT-AI/` (the design mockup) is ever touched.
- Everything runs in Docker only.

## Epics

| # | Epic | Sprints |
|---|------|---------|
| E1 | Traites API (CRUD, queue, documents) | 1, 2 |
| E2 | Verification & decision workflow | 3 |
| E3 | OCR/NLP async pipeline | 4 |
| E4 | Frontend — full design port | 5, 6 |
| E5 | Auth & hardening | 7 |
| E6 | Real OCR/extraction (VLM) | 8 |
| E7 | UI simplification + raw extraction audit log | 9 |

## Sprint plan

### ✅ Sprint 0 — Foundations (done, previous session)
Repo/Docker scaffolding, full DB schema (10 tables), migrations, seed data,
backend health check. 12/12 tests passing.

### ✅ Sprint 1 — Traites API: read & create (done)
**Goal**: the queue list and analysis-screen header have a real API behind
them.
- [x] 1.1 Pydantic schemas (`TraiteCreate`, `TraiteRead`, `TraiteDetail`, `TraitePage`, nested read schemas)
- [x] 1.2 `GET /api/traites` — list, filter by `statut`, paginated, sorted by remaining SLA (oldest `date_reception` first)
- [x] 1.3 `GET /api/traites/{id}` — detail, with documents/checks/decisions/champs/NLP eager-loaded
- [x] 1.4 `POST /api/traites` — create; auto-seeds the 4 mandatory `VerificationManuelle` rows
- [x] 1.5 Audit log write-through on every mutation
- [x] 1.6 Tests: schema validation, list/filter/pagination, create, 404/409 paths

21/21 tests passing (run twice), ruff clean, live-smoke-tested against the
real dev DB (created/listed the mockup's own traite `011570763437` through
the running API, then cleaned it up).

### ✅ Sprint 2 — Document upload (done)
**Goal**: recto/verso upload flow matching the design's dropzone contract
(both faces required, one of each).
- [x] 2.1 File storage abstraction (local volume now; swappable later) — `LocalFileStorage` behind a `get_storage()` FastAPI dependency (mirrors `get_session`), so tests override it to a throwaway temp dir instead of the real uploads volume.
- [x] 2.2 `POST /api/traites/{id}/documents` (face=recto|verso, content-type allowlist, 15 MB limit)
- [x] 2.3 `GET /api/traites/{id}/documents/{face}` (stream file back with correct content type)
- [x] 2.4 Reject duplicate face upload without explicit `?replace=true`
- [x] 2.5 Tests

30/30 tests passing (run twice), ruff clean, live-smoke-tested against the
real dev server and volume (uploaded a real file, confirmed it on disk
inside the container at `/app/uploads/<traite_id>/...`, downloaded it back
byte-for-byte, then cleaned up).

**Two real bugs caught and fixed mid-sprint, not shipped**:
1. `migrations/env.py` was missing `include_schemas=True` — without it,
   Alembic autogenerate can't see the `imx` schema at all and proposed
   *recreating* `imx.adherents/debiteurs/factures` (which already existed
   with data) as part of this sprint's migration. Caught by reading the
   generated migration before applying it, not by trusting the tool.
2. `python-multipart` wasn't in `requirements.txt` — FastAPI needs it for
   any endpoint accepting file uploads. Caught immediately by the test
   suite failing to even import the app.

### ✅ Sprint 3 — Manual verification & decision workflow (done)
**Goal**: port the mockup's blocking business rules server-side (single
source of truth instead of duplicated frontend JS).
- [x] 3.1 `PATCH /api/traites/{id}/verifications/{code}` (conforme/anomalie, or null to reset — mirrors the mockup's toggle)
- [x] 3.2 Server-side `bloque` + recommendation computation in `app/services/verification_rules.py` — a pure, DB/HTTP-free port of the mockup's `bloque`/`reco` logic, exposed on `GET /api/traites/{id}` as `bloque`/`motif_blocage`/`recommandation`
- [x] 3.3 `POST /api/traites/{id}/decisions` (validee/renvoi/fraude): validee is blocked by the rule above; renvoi/fraude are always available (matching the design, where those two buttons are never disabled) but require a comment; any decision is rejected once a traite already has one (a real-world guard the mockup, being a single-traite demo, never needed)
- [x] 3.4 Tests: 7 pure unit tests on the rules function (every reachable branch) + 14 integration tests through the real HTTP endpoints

50/50 tests passing (twice), ruff clean, live-smoke-tested end to end
against the real dev server: attempted validation with 0/4 checks (409),
marked all 4 conforme, validated successfully (201), confirmed
`traite.statut` flipped to "Validée" — then cleaned up.

**One design decision made explicit, not silently assumed**: the mandatory
comment rule from the design ("obligatoire si écart") is implemented for
renvoi/fraude now; extending it to validée needs the OCR/NLP écarts
computation (Sprint 4) to know whether there's anything to justify, so
validée has no comment requirement yet. Also noted: one branch of the
ported rule logic (`sig_tireur` statued-but-not-conforme while everything
else passes) is mathematically unreachable given today's 2-value
conforme/anomalie domain — true in the original mockup too — kept for
documentation value and future-proofing, not deleted as dead code.

### ✅ Sprint 4 — OCR/NLP async pipeline (done, one task carried forward)
**Goal**: real async processing, replacing the mockup's fake timer. Built
per the validated "pluggable stub" decision: the async infrastructure,
state machine, and NLP matching are all real and fully tested; the
extractor behind them is an honest, documented placeholder until real
OCR is evaluated (tracked in the backlog below).
- [x] 4.1 Celery + Redis added to docker-compose (`worker` service, `app/worker.py`)
- [x] 4.2 Processing state machine: `A_TRAITER` → (`POST .../analyse`) → `EN_COURS_OCR` → (task completes) → `CONTROLE_MANUEL_REQUIS` or `ECARTS_A_TRAITER`
- [x] 4.3 Extraction behind a pluggable `Extracteur` interface (`app/services/extraction.py`) — `StubExtracteur` honestly reports known traite fields (numero_lcn, montant, dates) consistently, a **real** French number-to-words conversion for montant en lettres (`app/services/nombres.py`, matches the design's exact example), and reports genuinely unknown fields (RIB, lieu, party names) as absent rather than invented
- [x] 4.4 NLP fuzzy match (rapidfuzz, `app/services/nlp_matching.py`) vs `imx.adherents`/`debiteurs` → `rapprochements_nlp`, resolving `traite.code_adherent`/`code_debiteur`
- [x] 4.6 `GET /api/traites/{id}/status` — the minimal polling contract ("waiting system")
- [x] 4.7 Tests: pure units for nombres/extraction/nlp_matching, integration for `executer_analyse`, a Celery-task-wrapper test (calls the task directly, no broker needed), and API tests for `/analyse` + `/status`
- [ ] **4.5 carried forward, not done**: mentions-obligatoires / date-rules read-model. Turns out to need a `Traite` → `imx.factures` link that doesn't exist yet (the "avance sur facture" check needs to know *which* invoice a traite is drawn against — not modeled by resolving adherent/debiteur alone). Moved to Sprint 6 (see below), where it belongs anyway since it's exactly what the analysis screen's right column needs.

104/104 tests passing (twice), ruff clean. Live-validated the *real* async
path end-to-end — not just the eager/direct-call test paths — created a
traite, uploaded real files, launched `/analyse`, watched the worker
receive and complete the task over real Redis (confirmed in its logs),
polled `/status` to completion, and inspected the persisted result.

**Three real issues caught, not shipped**:
1. `celery_app.autodiscover_tasks(["app.tasks"])` was wrong usage — it
   actually searches for an `app.tasks.tasks` submodule, not `app.tasks`
   itself. The worker started cleanly, connected to Redis, logged zero
   errors — and silently registered **zero tasks**. Only caught by reading
   the worker's own startup log (`[tasks]` section empty) during the live
   smoke test, not by any automated check. Fixed with an explicit import
   instead of relying on discovery convention.
2. Redis's default port 6379 collided with another local project's
   container. Fixed by defaulting `REDIS_PORT` to 6380 on the host side
   only (internal Docker networking is unaffected).
3. `meilleur_match("LA MEDITERRANEENNE", ...)` vs `"LA MÉDITERRANÉENNE"`
   scores 88.89, not the ≥90 I'd assumed writing the test — and more
   importantly, that's *below* the design's 95% auto-confirm threshold.
   Real accent-dropping OCR noise would currently push otherwise-correct
   matches into "needs review" more than necessary. Not fixed now (no real
   OCR output exists yet to validate a fix against) — tracked below.

### ✅ Sprint 5 — Frontend port I: login, topbar, queue (done)
- [x] 5.1 Design tokens (`theme.ts`) + global CSS (`styles/global.css`) — both copied verbatim from the validated TRAIT-AI mockup, not reinterpreted
- [x] 5.2 Login screen (no role picker, per the validated design decision)
- [x] 5.3 Topbar + profile dropdown/logout, wired to a (placeholder, client-only) `AuthContext` — real LDAP auth is still Sprint 7
- [x] 5.4 Queue list (dropzones, counters, filters, pagination) wired to the real Sprint 1–4 API, React Query for server state, React Router for navigation
- [x] 5.5 Tests: 16 Vitest/Testing-Library tests (Login, Topbar, QueuePage, format utils) + `tsc -b` clean + a real Playwright browser run (see below) — "responsive" isn't meaningfully testable under jsdom (no layout engine), so responsiveness was verified live in an actual browser instead, not faked as a jsdom assertion

**Two real gaps found and resolved before writing any frontend code** (both
already reflected in the backend endpoints/schemas above): the queue table
needs Tireur/Tiré **names**, not just codes (`tireur_nom`/`tire_nom` added
to `TraiteRead`, resolved via new `Traite.adherent`/`.debiteur`
relationships) — and a `GET /api/traites/counts` endpoint for the 5 status
cards, which Sprint 1 never scoped. Also added a small intake form (N°
L-CN, montant, dates) to the upload card: the mockup only ever demoed one
already-existing traite and never modeled how a *new* one gets these
values — this repo's own architecture decision (Sprint 0) is that they're
bordereau-declared at intake, so the UI needs a place to declare them.

**Validated live in a real browser (Playwright, no `chromium-cli` on this
host, so driven directly)**: login → queue navigation, protected routing,
profile dropdown/logout, and the responsive breakpoints at both desktop
and a 375px mobile viewport (confirmed zero horizontal overflow at both).

**One real, load-bearing bug caught only by this real-browser
verification** — every earlier "live smoke test" in this project used
`curl`, which does not enforce or even surface CORS. The frontend's every
API call was silently blocked by the browser: **the backend had no CORS
configuration at all.** Fixed (`CORSMiddleware` + `cors_allowed_origins`
setting) and covered by `test_cors.py`; re-verified live afterward with
zero console errors. This is the clearest evidence yet in this project for
why curl-only validation is not sufficient for anything the browser itself
enforces.

### ✅ Sprint 6 — Frontend port II: analysis screen + waiting system (done)
- [x] 6.0 **Carried forward from Sprint 4**: mentions-obligatoires / date-rules read-model. `trouver_facture_correspondante` (`app/services/mentions_rules.py`) matches on (code_adherent, code_debiteur) then picks the facture whose `montant_net` is closest to the traite's montant. Corrected mid-build: an early version duplicated the already-existing "champs dupliqués" table instead of building the design's actual (distinct) legal-presence checklist — fixed to 6 of the 8 mentions (2 have no data source, documented in the module).
- [x] 6.1 Document viewer — **per your call**: the real uploaded recto/verso image via `<img src=".../documents/{face}">`, no overlays. PDFs get an "Ouvrir le PDF" link instead of an inline render.
- [x] 6.2 Verdict / mentions / duplicate-fields / date-rules / NLP panels — all backed by 6.0 and Sprint 4's real data, not mockup fixtures
- [x] 6.3 Manual verification checklist wired to the Sprint 3 PATCH endpoint
- [x] 6.4 Decision panel wired to the Sprint 3 decisions endpoint, showing the exact block reason when disabled
- [x] 6.5 Polling-driven waiting panel — while `statut === "En cours OCR"`, polls `GET .../status` every 2s and invalidates the detail query once `en_cours` flips false (replaces the mockup's fake `setInterval` phase simulation)
- [x] 6.6 Tests: backend — 10 pure unit tests + 1 end-to-end integration test (real `executer_analyse` → real API response); frontend — 8 component tests for `AnalysisPage`

108/108 tests pass twice (backend), 24/24 (frontend), clean `tsc -b`. **Fully
live-validated in a real browser**, not just curl or unit tests: logged in,
filled the intake form, uploaded a real decodable JPEG, launched analysis,
watched it complete via the actual polling mechanism, confirmed the image
genuinely renders (`naturalWidth`/`naturalHeight` from a real `load`
event, not just DOM presence), marked all 4 manual checks, watched
"Valider" go from disabled-with-reason to enabled, validated, and
confirmed the status flip to "Validée" via the real API afterward. Zero
console errors throughout.

**Real issues caught, not shipped:**
1. A first version of `evaluer_mentions` accidentally re-derived the
   already-existing "champs dupliqués" comparison (numero_lcn, montant...)
   instead of the design's actual, *different* "mentions obligatoires"
   legal-presence checklist (nom du tiré, lieu de paiement, ...) — caught
   by re-reading the design's own two panels side by side before trusting
   the first implementation, not after.
2. Three progressively-deeper test-isolation bugs in the new integration
   test, each only visible running the *full* suite, not the test alone:
   `imx.*` rows aren't truncated between tests (only `traites` is) so
   hardcoded seed codes shared with another test file collided; the
   cleanup then hit `ForeignKeyViolation` because `executer_analyse` had
   already pointed the traite's FKs at the very rows being deleted; fixed
   by reusing the same `TRUNCATE traites CASCADE` pattern already
   established for exactly this reason elsewhere in the suite.
3. Two apparent live-browser bugs (an empty document viewer, then
   `naturalWidth: 0`) turned out on inspection to both be test-harness
   artifacts — fake non-image upload bytes the first time, a premature
   synchronous check before the image's `load` event the second — not
   application bugs. Worth recording *because* the instinct to keep
   digging until the real cause was confirmed (rather than reporting
   either a false "it's broken" or a false "it's fine") is what actually
   separates a genuine live-browser validation from a superficial one.

### ✅ Sprint 7 — Auth & hardening (done)
- [x] 7.1 LDAP bind (`ldap3`) replacing the placeholder client-only login — `app/services/ldap_auth.py` attempts a real bind as the target user (never reads/stores the password) against a real, throwaway, seeded `bitnamilegacy/openldap` dev/CI container (`ldap` service in docker-compose.yml). Same generic 401 for "wrong password" and "unknown user" so the endpoint can't be used to enumerate usernames.
- [x] 7.2 Session/JWT + frontend auth guard — `POST /api/auth/login` issues an HS256 JWT (`app/services/jwt_auth.py`, 8h expiry); every `/api/traites/*` route now requires it via a router-level `Depends(get_current_user)` (`app/api/deps.py`), and every audit field that used to hardcode `"system"` now carries the real authenticated username. Frontend: `AuthContext` calls the real endpoint, persists `{token, username}` to `localStorage`, and forces a logout on any `401` from anywhere in the app (token expiry included) — not just at the login form.
- [x] 7.3 End-to-end test pass — backend: `test_auth.py` (6 tests: valid login, wrong password, unknown user gets the *same* 401, empty credentials, protected route without a token, protected route with a garbage token), all against the real LDAP container, not a mock. Frontend: `LoginPage`/`AnalysisPage` tests updated for the now-async, real login call. **Live-validated in a real browser end to end**: unauthenticated redirect → wrong password rejected → real LDAP bind succeeds → session survives a full page reload → profile-dropdown logout → redirected again; then a full second pass uploading a real image and confirming the recto renders through the new authenticated blob-fetch path (see bug #3 below), with zero console errors either time.
- [x] 7.4 Production Dockerfile hardening — `back/Dockerfile` and `front/Dockerfile` are now multi-stage (`dev`/`production`; `front/` adds an intermediate `build` stage). Production backend: only `requirements.txt` (no pytest/ruff/httpx), no bind mount, runs as a non-root `app` user, no `--reload`. Production frontend: built by Vite then served by `nginxinc/nginx-unprivileged` (non-root by construction) with a reverse proxy to the backend (`front/nginx.conf`) so the browser only ever talks to one origin — no CORS configuration needed in production. `docker-compose.yml`'s `backend`/`worker`/`frontend` now pin `target: dev` explicitly, since an unpinned multi-stage build defaults to the *last* stage (`production`) — that would have silently broken local dev the moment this landed.
- [x] 7.5 Deployment docs — new `docker-compose.prod.yml` (production targets, no bind mounts, no default secrets — every security-relevant var is `${VAR:?...}`-required) and `.env.prod.example`; README.md gets a "Production deployment" section.

Both live-validated end to end under a throwaway `-p trait-prod-smoketest`
project, not just built: `alembic upgrade head` against a fresh prod
database, `/api/health` returned `{"environment":"production"}` *through*
nginx's reverse proxy (not hit directly), the SPA's `index.html` served
correctly, and — in a real browser — a full login using the bundled demo
LDAP directory, all the way to the queue page rendering, zero console
errors. Confirmed non-root with `docker exec ... id` (`uid=999(app)` /
`uid=101(nginx)`, not root) rather than trusting the Dockerfile alone.
Image size, measured, not estimated: backend/worker 422 MB → 373 MB,
frontend 632 MB → 74 MB (dev's full `node_modules` + Vite dev server vs.
a static bundle + nginx).

123/123 backend tests pass twice, 26/26 frontend, clean `tsc -b`, clean `ruff check`.

**Real issues caught, not shipped:**
1. `bitnami/openldap:2.6` doesn't exist any more — Bitnami retired free
   versioned tags on Docker Hub in 2025; the pullable free equivalent is
   `bitnamilegacy/openldap:latest`. Found by actually trying to pull it,
   not by assuming the tag from memory.
2. The seeded LDAP tree crashed on boot (`ldap_add: Already exists (68)`)
   because the deprecated `LDAP_USER_DC=users` env var duplicates the
   image's own default `ou=users` creation. Root-caused by running the
   image standalone with `BITNAMI_DEBUG=true` rather than guessing from
   the truncated compose logs — fixed by dropping the var and taking the
   default. Separately, the seeded users turned out to be keyed by `cn=`,
   not `uid=` as first assumed — confirmed with a real `ldapsearch`/
   `ldapwhoami` against the running container before wiring
   `ldap_user_dn_template` to match, rather than trusting the guess.
3. Every `<img src>`/`<a href>` pointing at a document (`DocumentViewer` in
   `AnalysisPage`) broke once the traites router required a Bearer token —
   a plain browser-native URL request can't carry an Authorization header.
   Fixed by fetching the bytes through the authenticated `request()` path
   and rendering a `URL.createObjectURL` blob instead; only found by
   actually uploading a real image live and watching the request return
   401, not by reasoning about it in the abstract.
4. A real race condition: the JWT was attached to outgoing requests from
   inside an `AuthContext` `useEffect`, but React runs a *child's* effects
   before its parent's — so on a full page reload, `QueuePage`'s
   data-fetching effect fired (and got a real 401, forcing a logout) before
   `AuthProvider`'s effect had set the token. Only visible on an actual
   reload in a real browser, never in the component tests (which never
   remount from a cold module state). Fixed by having `api/client.ts` read
   the persisted token synchronously at module load instead of waiting for
   a `useEffect`.
5. A copy-paste variable-rename bug (`STORAGE_KEY` renamed to
   `AUTH_STORAGE_KEY` in only one of four usages) crashed the login form
   with a `ReferenceError`, and a subsequent blind `replace_all` then
   *over*-corrected it into `AUTH_AUTH_STORAGE_KEY` by matching the
   substring inside its own already-correct occurrences. Caught by the
   live browser test surfacing a `pageerror`, not by re-reading the diff —
   a reminder that a passing typecheck/test run doesn't catch a renamed
   identifier that's still syntactically valid in every file it appears in.
6. Vite's dev server silently kept serving stale, pre-edit source after
   every fix above — file-change events from the Windows-host bind mount
   never reach chokidar's default watcher inside the Linux container, so
   edits had no effect until either a container restart or (the actual
   fix) `server.watch.usePolling` in `vite.config.ts`. Confirmed by curling
   the dev server's served source directly and diffing it against the file
   on disk, rather than assuming a passed test meant the running app had
   the fix.

### ✅ Sprint 8 — Real OCR/extraction via VLM (done, accuracy pilot deferred)
**Goal**: replace `StubExtracteur` with a real vision-capable LLM behind
the exact same `Extracteur` seam Sprint 4 designed for this — per your
call, switchable by one env var rather than a code change, since which
provider is allowed to see scanned bank instruments is a data-residency
decision, not an engineering one.
- [x] 8.1 `app/services/vlm_extraction.py` — `VlmExtracteur`, one
  implementation shared by both providers (Azure OpenAI and any local
  OpenAI-Chat-Completions-compatible server speak the identical Chat
  Completions API; only client construction differs). Sends recto+verso as
  base64 `image_url` parts alongside a French prompt asking for both
  physical occurrences of each duplicated field (numero_lcn, montant en
  chiffres/lettres, échéance, date de création, RIB, lieu) plus the
  tireur/tiré/ordre free text, as strict JSON. Skips the model call
  entirely (reports absence, doesn't crash) for a PDF face — vision chat
  APIs take images, not PDFs, and that isn't implemented yet.
- [x] 8.2 `OCR_PROVIDER` setting (`stub` / `azure_openai` / `local_llm`)
  in `app/core/config.py`, defaulting to `stub` — an unconfigured
  deployment must never silently start making real, possibly-billed
  external calls. `get_extracteur()` factory replaces the hardcoded
  `StubExtracteur()` in the Celery task (`app/tasks/traite_processing.py`)
  — `executer_analyse` itself didn't need to change at all, exactly the
  payoff of having built it against an interface from the start.
- [x] 8.3 `docker-compose.yml` gets a real `ollama` service (an actual
  local OpenAI-compatible vision model server, not a stub) for the
  `local_llm` path — `make ollama-pull` fetches a model into it. Azure
  OpenAI needs real tenant credentials this environment doesn't have, so
  it's covered by unit tests only (see below); local_llm is the one path
  that could be — and was — validated against a genuinely running model.
- [ ] 8.4 Real OCR accuracy pilot against actual bilingual FR/AR scans —
  explicitly out of scope here. This sprint proves the *plumbing* (image
  in, structured fields out, both providers swappable); it says nothing
  about extraction *accuracy* on a real instrument, which needs real
  sample scans this project doesn't have.

13 new backend unit tests: 12 in `test_vlm_extraction.py` (JSON-response
parsing — raw, markdown-fenced, prose-wrapped, unparseable — the full
champs/parties mapping against a fake client, also asserting the model
actually receives both images and not just the prompt, the PDF-skip path,
both providers' client-construction functions, and `get_extracteur`'s
dispatch for default/local_llm/unknown-provider) plus 1 in
`test_traite_processing.py` for the real bug below — all against
dependency-injected fakes, never a real paid Azure call in the suite.
136/136 backend tests pass twice, clean `ruff check`.

**Live-validated against a real running model, not just unit tests**: the
`ollama` service was actually brought up, `moondream` (a small, real,
general-purpose vision model — no accuracy claims made for it, see 8.4)
pulled into it with `make ollama-pull`, `OCR_PROVIDER=local_llm` set, and a
full traite created → uploaded → analysed through the real browser exactly
like every other live-validated sprint. Confirmed in the worker's own
logs: a genuine `POST http://ollama:11434/v1/chat/completions` request,
200 response, real (if generic — moondream isn't document-tuned) model
output.

**One real bug found by that live run, not shipped:**
1. moondream's response ignored the "respond only with JSON" instruction
   entirely and described the image conversationally instead of extracting
   fields — an entirely realistic failure mode for a real external model,
   not a test artifact. `_parser_reponse_json` correctly rejected it and
   raised — but `executer_analyse` had no handling for that exception at
   all, so it propagated out of the Celery task uncaught. The traite was
   left permanently stuck in `EN_COURS_OCR`: the task technically
   "succeeded" from Celery's point of view (no retry, no error surfaced
   anywhere a human would see it), while the frontend polled forever for a
   status that would never change. Only visible by actually watching a
   real model give a real bad response in the real running pipeline — no
   unit test using a hand-picked "malformed JSON" fixture would have
   caught the *consequence* of that failure going unhandled, only that the
   parser itself raised correctly in isolation. Fixed: `executer_analyse`
   now catches any extraction failure, marks the traite `ECARTS_A_TRAITER`
   (the same honest "needs review" status a low-confidence NLP match
   already produces) and writes an `analyse_echouee` audit entry with the
   real error message — re-validated live afterward: the same flow now
   resolves to `Écarts à traiter` within seconds instead of hanging.

### ✅ Sprint 9 — Decision panel removed, raw-SQL extraction audit log (done)
**Per your call.**
- [x] 9.1 Removed the "Décision du caissier" block entirely from
  `AnalysisPage.tsx` (the `DecisionCard` component, its JSX usage, the
  `commentaire` state, and the `decisionMutation`) — not hidden, deleted.
  **Real functional consequence, flagged not buried**: `POST
  /api/traites/{id}/decisions` (Sprint 3) and its `decisions` table are
  still there and still tested — nothing server-side was touched — but
  there is now **no way left in the UI to validate, renvoyer, or signaler
  fraude on a traite**. Say the word if you want that reinstated in some
  form, or left as-is while the workflow gets reconsidered.
- [x] 9.2 A new `extractions_ia` table — written and read via **raw SQL
  through `psycopg` directly** (`app/services/extraction_log.py`), not the
  SQLAlchemy ORM used everywhere else in this app, per your ask. DDL is
  hand-written raw SQL too (`migrations/versions/0004_extractions_ia_log.py`,
  `op.execute(...)` rather than Alembic's `op.create_table`), since no ORM
  model exists for this table at all. Columns: `traite_id` (FK, cascade
  delete), `fournisseur`, `modele`, `succes`, `reponse_brute` (the model's
  actual raw text — this didn't exist anywhere before; a failed extraction
  used to only leave a 200-char-truncated error string in `audit_log`),
  `erreur`, `duree_ms`, `cree_le`. Indexed on `traite_id`.
- [x] 9.3 Logging is written via its own short-lived autocommit connection
  — deliberately independent of `executer_analyse`'s SQLAlchemy
  transaction, the correct shape for an audit log (a log entry must
  survive even when the business transaction it's observing fails or
  never commits) — and never raises: a logging failure is caught and
  warned, never allowed to take down the pipeline it's observing.
- [x] 9.4 Wired into `VlmExtracteur.extraire()` (both providers, one code
  path) — logs every real model call attempt, success or failure, timed.

8 new backend tests: 5 in `test_extraction_log.py` running against the
**real test database** (round-trip write/read, a failed attempt with its
full raw response, chronological ordering, per-traite scoping, and proving
the "never raises" guarantee against an actual FK violation — not asserted
in the abstract), plus 2 in `test_vlm_extraction.py` (the log call is
mocked there, same boundary-mocking pattern as the OpenAI client, since
that suite is meant to run network/DB-free) and 1 schema-shape test in
`test_migrations.py`. 3 frontend tests removed (`renvoi`/`valider`/
`already-decided` — they tested UI that no longer exists). **143/143
backend, 23/23 frontend**, clean `tsc -b`, clean `ruff check`.

**Real bug caught by live validation, not shipped**: the new migration was
never applied to the *dev* database — only the test suite's session
fixture auto-migrates `trait_ai_test`. Running the new code live against
dev hit `psycopg.errors.UndefinedTable: relation "extractions_ia" does not
exist` — and that's exactly what proved 9.3's "never raises" design
actually holds under a real failure, not just a mocked one: the traite
still resolved correctly to `Écarts à traiter`, extraction-log write
failure and all. Fixed by actually running `alembic upgrade head` against
dev (a normal, expected step — not a code bug), then re-validated: real
`moondream` call, full untruncated raw response landed in `extractions_ia`
(`succes=false`, `duree_ms=3650`), traite still resolved correctly. This
whole check ran directly against `executer_analyse`, deliberately
bypassing Celery — the live `worker` and `.env` are currently pointed at a
real Azure OpenAI resource with real credentials, and validating this
sprint's changes didn't require spending your Azure budget.

### ✅ Sprint 10 — Local login replaces LDAP (done)
**Per your call** — LDAP directory (`bitnamilegacy/openldap`, dev/CI-only)
dropped entirely in favor of this app owning its own identity store.

- [x] 10.1 New `users` table (`app/db/models/user.py`) —
  `id`/`username` (unique)/`password_hash`/`is_active`/timestamps.
  Migration `49a3fe136ee4_users_table`; autogenerate's usual false-positive
  "drop `extractions_ia`" (that table is invisible to `Base.metadata` by
  design — raw SQL only, see Sprint 9) stripped by hand from both
  `upgrade()`/`downgrade()`.
- [x] 10.2 Argon2id password hashing (`app/services/password_hash.py`, via
  `argon2-cffi`) — OWASP's current default recommendation. A dummy-hash
  verification path (`verify_dummy_password`) runs when a username doesn't
  exist, so an unknown-user login takes about as long as a real user's
  wrong-password one — without it, real Argon2 verification only running
  for existing usernames is a response-time side channel that leaks
  exactly the fact the identical 401 message is meant to hide.
- [x] 10.3 `app/services/local_auth.py` replaces `ldap_auth.py` — looks the
  user up, verifies the hash off the event loop via `run_in_threadpool`
  (Argon2 verification is deliberately slow, same reasoning the earlier
  LDAP bind and the disk I/O in `storage.py` already use that pattern
  for). `routes/auth.py` updated accordingly; `ldap3` dependency removed.
- [x] 10.4 `scripts/seed.py` now also seeds the two dev accounts
  (`h.mansouri`/`a.trabelsi`, both `secret123`) — real Argon2 hashes, not
  fixture data. New `scripts/create_user.py`: a minimal, idempotent
  create-or-reset-password tool, deliberately separate from `seed.py`
  because that script also inserts fake `imx.*` example companies, which
  would be wrong to run against a real production database. Documented as
  the production account-creation path in `.env.prod.example`.
- [x] 10.5 `docker-compose.yml`/`.prod.yml`, `.env*` — `ldap` service,
  volume, and every `LDAP_*` var removed.

**166/166 backend tests, twice** (`test_auth.py` rewritten against a real
seeded row in the real test database via a new `seed_test_user` fixture,
not mocked; new `test_password_hash.py` for the hashing primitives),
**26/26 frontend** (only one test needed a rename — the frontend never had
LDAP-specific code, it just calls `/api/auth/login`). `ruff`/`tsc -b`
clean. Live-verified against the real running dev stack: seeded the dev DB,
logged in for real over HTTP, made an authenticated request, confirmed a
wrong password still 401s.

### ✅ Sprint 11 — Worker/Celery/Redis removed, analysis runs in `backend` (done)
**Per your call** — asked to drop the separate `worker` process entirely
and run OCR/NLP analysis inside `backend`; confirmed the mechanism as
FastAPI `BackgroundTasks` (still 202-immediately, still polled via
`GET .../status`, only the internal dispatch changes) rather than any
alternative that would touch the frontend's polling contract.

- [x] 11.1 `app/worker.py` (the Celery app instance) deleted.
  `app/tasks/traite_processing.py`'s `launch_traite_analysis` (a
  `@celery_app.task`) became a plain function `run_traite_analysis` —
  same body (sync engine via `SYNC_DATABASE_URL_OVERRIDE`-aware
  `_sync_database_url()`, `execute_analysis`, commit, dispose). Its
  docstring records the one real behavior change this trades away: a
  background task now lives only as long as the `backend` process that
  started it — a restart mid-analysis loses it silently (no retry, no
  record beyond whatever was already committed), where Celery+Redis
  queued durably across restarts. Accepted deliberately for simplicity;
  nothing in this app's actual usage pattern (interactive, one analysis
  at a time, a human waiting on the result) depends on that durability.
- [x] 11.2 `routes/traites.py`'s `lancer_analyse` takes a
  `BackgroundTasks` param and calls
  `background_tasks.add_task(run_traite_analysis, str(traite_id))`
  instead of `.delay(...)`.
- [x] 11.3 `celery`/`redis` dropped from `requirements.txt`; `redis_url`
  dropped from `core/config.py`; the `redis` and `worker` services and
  every `REDIS_*`/broker env var removed from both compose files and
  `.env*` — `OCR_PROVIDER`/`AZURE_OPENAI_*` moved onto `backend` itself,
  since that's where extraction now actually runs.
- [x] 11.4 Tests: `test_celery_task.py` renamed to
  `test_traite_analysis_task.py`, calling `run_traite_analysis` directly
  (no Celery wording left). `test_analyse_endpoint.py`'s dispatch spy now
  monkeypatches `run_traite_analysis` itself rather than a `.delay()`
  attribute — works because Starlette's `BackgroundTasks` run via
  `run_in_threadpool` as part of the same ASGI call chain, so with the
  `ASGITransport`-backed test client (no real network hop) the task has
  already run by the time `await client.post(...)` returns.
- [x] 11.5 Docs updated: README (architecture table, quickstart, project
  layout, testing section, production section), both `trait-ai-app-dev`/
  `trait-ai-app-ocr-providers` skills, `trait-ai-app-sprint-workflow`'s
  "where things stand" note.

**Real issue caught, not shipped**: moving `OCR_PROVIDER`/`AZURE_OPENAI_*`
onto `backend` means the same container `pytest` runs in now also carries
the real Azure credentials from `.env` (previously only `worker` saw
them). Two tests in `test_vlm_extraction.py`
(`test_client_azure_openai_requires_full_configuration`,
`test_get_extractor_defaults_to_stub`) built a bare `Settings()`/
`Settings(ocr_provider="azure_openai")` expecting empty/default fields —
pydantic-settings reads env vars over field defaults, so both silently
picked up the real ambient config and failed (one didn't raise, the other
built a `VlmExtractor` instead of `StubExtractor`). Fixed by making both
tests explicit about every field they care about instead of relying on
ambient env being clean — the correct fix, since a real deployment
legitimately needs those vars on the same service the tests run in now.
Live-verified separately: temporarily flipped `.env` to
`OCR_PROVIDER=stub`, recreated `backend`, drove a real HTTP flow
(login → create traite → upload recto/verso → `POST .../analyse` → poll
`.../status`) against the running container over the network — 202
immediately, `en_cours` true then false, final statut
`Écarts à traiter` (expected, `StubExtractor` has no party text to match)
— then reverted `.env` and recreated `backend` again before committing.

## Backlog (not yet scheduled)

- Party/entity unification (a company can be both an `adherent` and a
  `debiteur` — currently two unrelated codes; revisit if the business
  actually needs that link modeled).
- RIB checksum validation (currently structural length only, no modulo
  check).
- Accent normalization before NLP matching: measured (not assumed) that an
  accent-only difference — "LA MEDITERRANEENNE" vs "LA MÉDITERRANÉENNE" —
  scores 88.89 with rapidfuzz's WRatio, *below* the design's 95%
  auto-confirm threshold (see `test_minor_ocr_style_variation...` in
  `test_nlp_matching.py`). Once real OCR exists and starts occasionally
  dropping accents, this will quietly push otherwise-correct matches into
  "needs manual review" more often than necessary. A pre-match
  normalization step (strip accents on both sides before scoring) is a
  cheap, low-risk fix — deliberately not done now since there's no real OCR
  output yet to validate it against.
