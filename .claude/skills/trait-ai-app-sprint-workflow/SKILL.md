---
name: trait-ai-app-sprint-workflow
description: The working agreement for continuing TRAIT-AI-APP development in validated sprints — BACKLOG.md conventions, the never-mock-what-you-can-run-for-real discipline, and what "done" actually requires before moving to the next task.
---

# Continuing TRAIT-AI-APP development

This project has been built sprint by sprint (see `BACKLOG.md` — the
living source of truth for what's shipped and what's next). Continuing it
means inheriting the same discipline, not just writing more code.

## Hard rules

- **Never modify `TRAIT-AI/`** (the sibling design-mockup folder) — it's
  the reference design this app ports functionality from, and is read-only
  for this project, permanently.
- **Everything runs in Docker.** There is no supported "run it directly on
  the host" path.
- **A sprint/task isn't done until**: code written, automated tests
  written and passing *inside Docker, run twice in a row* (catches
  flakiness, not just "did it pass once"), and `BACKLOG.md` updated with a
  real summary before moving on.

## The validation discipline that's paid off repeatedly

Every real bug this project has found and fixed was caught by one of two
things: reading generated code/output before trusting it (not just
running it), or driving the actual running app for real — a real browser
via Playwright, a real LDAP bind, a real Postgres migration applied to a
real database, a real local LLM given a real image. `curl`-only or
mocked-everything validation has repeatedly missed real, load-bearing
bugs in this exact codebase (a missing CORS config invisible to curl, a
`useEffect`-ordering race invisible to component tests, a real model
ignoring its own JSON-format instruction). When a change touches the
browser, the database, auth, or an external service, validate it against
the real thing before calling it done — mocking is for the *inputs* you
don't control (a paid external API you don't want to bill on every test
run), never a substitute for exercising your own code for real at least
once.

## Working with `BACKLOG.md`

- One sprint = one coherent, independently testable slice.
- Each sprint's write-up includes real test counts (not "tests pass," the
  actual before/after numbers) and, where relevant, a "real issues
  caught, not shipped" section — this project's history of genuine bugs
  found mid-build, with root cause and fix. This is deliberate: it's the
  evidence that validation actually happened, not just a checklist being
  ticked.
- Flag genuine architectural forks to the user rather than picking
  silently — e.g. "which OCR provider," "which document-viewer approach"
  were both raised as explicit decisions in this project's history, not
  assumed. Implementation *details* don't need this; decisions with real
  tradeoffs the user hasn't stated a preference on do.

## Where things stand (check `BACKLOG.md` for the current, authoritative version)

Sprints 0–9 shipped: DB foundations, Traites API, document upload,
verification/decision workflow (backend only as of Sprint 9 — see below),
the OCR/NLP async pipeline with real VLM extraction (Azure OpenAI — see
the `trait-ai-app-ocr-providers` skill), the full frontend port, real
JWT auth, production Docker hardening, and a raw-SQL extraction audit log.
Two things worth knowing before touching related code:

- The "Décision du caissier" UI panel was removed entirely (Sprint 9, per
  explicit request) — the backend decision endpoint/table are untouched
  and tested, but there is currently no UI path to create one. Don't
  "fix" this by guessing a redesign; ask first.
- Real extraction *accuracy* against actual bilingual FR/AR bank
  instruments has never been evaluated — only the plumbing (image in,
  structured data out) has been proven. Don't treat a clean synthetic-test
  run as an accuracy claim.
- Changes made after Sprint 9, not yet reflected in BACKLOG.md's own sprint
  numbering, but real and tested: (1) `local_llm`/the bundled `ollama`
  service were dropped entirely — `OCR_PROVIDER` is `stub`/`azure_openai`
  only now. (2) The queue screen's intake form (N° L-CN/montant/dates typed
  in before upload) was removed — a traite is created from just the scans,
  with those fields server-generated as placeholders then overwritten by
  `execute_analysis` once extraction agrees on real values
  (`_promote_canonical_identity`). (3) Login moved off LDAP onto a local
  `users` table (Argon2id via `app/services/password_hash.py`) —
  `make seed` (dev) or `scripts/create_user.py` (anywhere, including
  production) creates accounts now; nothing does it automatically the way
  the old LDAP container's env vars did. (4) The separate `worker`
  container and Celery+Redis broker were removed entirely (Sprint 11) —
  the OCR/NLP pipeline now runs as a FastAPI `BackgroundTasks` job inside
  `backend` itself. See `back/app/tasks/traite_processing.py`'s docstring
  for the accepted tradeoff (a running task is lost if `backend` restarts
  mid-analysis) and why it was accepted.

Unscheduled backlog items (RIB checksum validation, accent normalization
for NLP matching, adherent/debiteur party unification) are listed at the
bottom of `BACKLOG.md` with the reasoning for why each was deferred — read
that reasoning before picking one up, it's often "no real data exists yet
to validate a fix against," not "not important."
