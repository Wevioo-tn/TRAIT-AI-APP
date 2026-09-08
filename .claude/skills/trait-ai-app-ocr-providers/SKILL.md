---
name: trait-ai-app-ocr-providers
description: Switch and validate TRAIT-AI-APP's real OCR/extraction backend — stub / Azure OpenAI — including the env-var reload gotcha and the real failure modes already found.
---

# Real OCR/extraction: stub or Azure OpenAI

`OCR_PROVIDER` in `.env` picks the extraction backend
(`get_extractor()` in `back/app/services/vlm_extraction.py`). Only two
values exist: `stub` (default, safe) and `azure_openai` (the only real
provider). A local/self-hosted option (`local_llm`, backed by a bundled
`ollama` service) existed earlier in this project and was removed per an
explicit call to keep the stack simple — see `BACKLOG.md`'s Sprint 8 notes
for that history; don't reintroduce it without checking why it was there
and why it was dropped.

**The one rule that catches everyone at least once**: editing `.env`
does *nothing* until the `backend` container is recreated — it reads env
vars once, at container start, not live (extraction runs as a FastAPI
background task inside `backend` itself, not a separate process).

```bash
docker compose up -d backend
```

## `stub` (default, safe)

Never reads the image at all — `StubExtractor` echoes back already-known
fields and reports the rest as absent. No network calls, no cost, no
setup. This is what ships when `OCR_PROVIDER` is unset.

## `azure_openai` — needs a real Azure OpenAI resource

From the Azure portal: the resource endpoint, an API key, and the
**deployment name** (not the base model name) of a vision-capable model.

```
OCR_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<your key>
AZURE_OPENAI_DEPLOYMENT=<your deployment name>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```
Then `docker compose up -d backend`. Missing config fails fast with a
clear `RuntimeError` in `docker compose logs backend` when the background
task runs (not at container startup) — no silent no-op. **Every launch
sends real image bytes to Azure and is billed** — be deliberate about
testing this path.

Not every deployment accepts every Chat Completions parameter — found
live: a "gpt-6-astra" deployment rejected `temperature=0` outright
("Unsupported value: 'temperature' does not support 0.0 with this model.
Only the default (1) value is supported."), the way newer reasoning-style
models often do. `VlmExtractor` deliberately doesn't pass `temperature` at
all for exactly this reason — don't add it back without checking whether
the deployment you're pointing at supports it.

## Validating a code change without spending anyone's Azure budget

If `.env` is currently configured for `azure_openai` (check before doing
anything that triggers analysis!), don't run a live browser upload/launch
flow — it dispatches to whatever the running `backend` is configured for,
and there's no way to route just one task to a different provider.

For changes to `execute_analysis`/the pipeline around extraction (not the
extraction call itself), bypass the background task with a one-off script
using `docker compose run --rm -e OCR_PROVIDER=stub backend python -c "..."`
that calls `execute_analysis(...)` directly against a real traite with
`StubExtractor` (or a small fake `Extractor` built for the scenario, the
way `back/tests/test_traite_processing.py` does with `_FakeExtractor`) —
same pattern as that test file. This never touches the live `backend`
container's own environment or the real Azure resource.

For changes to `VlmExtractor` itself (the prompt, JSON parsing, request
shape), `stub` can't help — it never calls the real code path at all.
Use the dependency-injected fake client in
`back/tests/test_vlm_extraction.py` instead (pure unit test, no network),
or accept the real Azure call if you specifically need to validate against
the real API.

## Real failure mode already found (not hypothetical)

Small/general-purpose vision models frequently **ignore** the "respond
only with JSON" instruction and describe the image conversationally
instead (confirmed live, historically, against a local model this project
no longer bundles — but the same failure shape is possible from any real
model). This is expected, not a bug — `_parse_json_response` rejects it
and `execute_analysis` resolves the traite to `Écarts à traiter` with the
real error in `audit_log` (`analyse_echouee`) and the **full raw
response** in the `extractions_ia` table (`app/services/extraction_log.py`
— raw SQL via `psycopg`, not the ORM). If a traite seems stuck instead of
resolving to that status after a failed extraction, that's a real
regression — check `app/services/traite_processing.py`'s
`except Exception` handling around the extraction call first.

## Reading what a model actually said

```sql
-- via `docker compose exec postgres psql -U trait -d trait_ai`
SELECT fournisseur, modele, succes, reponse_brute, erreur, duree_ms, cree_le
FROM extractions_ia WHERE traite_id = '<uuid>' ORDER BY cree_le;
```
Or programmatically: `app.services.extraction_log.list_extractions(traite_id)`.

Accuracy of extraction (as opposed to the plumbing above) has not been
evaluated against real bilingual FR/AR bank instruments — see
`BACKLOG.md`'s "Backlog (not yet scheduled)" section. Don't treat a clean
run against a synthetic test image as evidence of real-world accuracy.
