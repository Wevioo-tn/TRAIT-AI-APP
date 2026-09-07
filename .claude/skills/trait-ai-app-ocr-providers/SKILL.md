---
name: trait-ai-app-ocr-providers
description: Switch and validate TRAIT-AI-APP's real OCR/extraction backend — stub / Azure OpenAI / local OpenAI-compatible LLM (bundled ollama) — including the env-var reload gotcha and the real failure modes already found.
---

# Real OCR/extraction: stub, Azure OpenAI, or a local LLM

`OCR_PROVIDER` in `.env` picks the extraction backend
(`get_extractor()` in `back/app/services/vlm_extraction.py`). Which
provider is *allowed to run* is a data-residency/compliance decision, not
a technical one — see `BACKLOG.md`'s Sprint 8 notes before changing the
default for anyone other than local testing.

**The one rule that catches everyone at least once**: editing `.env`
does *nothing* until the `worker` container is recreated — Celery reads
env vars once, at container start, not live.

```bash
docker compose up -d worker
```

## `stub` (default, safe)

Never reads the image at all — `StubExtractor` echoes back already-known
fields and reports the rest as absent. No network calls, no cost, no
setup. This is what ships when `OCR_PROVIDER` is unset.

## `local_llm` — no external account needed

```bash
docker compose up -d                # brings up the bundled `ollama` service too
make ollama-pull                    # pulls "llava" (Makefile default, ~4.7GB)
# or, smaller/faster but worse at following the "respond only JSON" instruction:
make ollama-pull MODEL=moondream    # ~1.7GB — what was actually validated live in this project
docker compose exec ollama ollama list   # confirm it landed
```

In `.env`:
```
OCR_PROVIDER=local_llm
LOCAL_LLM_MODEL=moondream   # must exactly match what you pulled
```
Then `docker compose up -d worker` and `docker compose logs -f worker` to
watch the real `POST http://ollama:11434/v1/chat/completions` calls.

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
Then `docker compose up -d worker`. Missing config fails fast with a
clear `RuntimeError` in `docker compose logs worker` when a task runs
(not at container startup) — no silent no-op. **Every launch sends real
image bytes to Azure and is billed** — be deliberate about testing this
path, and never trigger it just to validate an unrelated code change when
`local_llm` or a bypass-Celery script (below) would do.

## Validating a code change without spending anyone's Azure budget

If `.env` is currently configured for `azure_openai` (check before doing
anything that triggers analysis!), don't run a live browser upload/launch
flow — it dispatches to whatever the persistent `worker` is configured
for, and there's no way to route just one task to a different provider.
Instead, bypass Celery entirely with a one-off script using
`docker compose run --rm -e OCR_PROVIDER=local_llm -e LOCAL_LLM_MODEL=moondream backend python -c "..."`
that calls `execute_analysis(...)` directly against a real traite — same
pattern as `back/tests/test_traite_processing.py`. This never touches the
live `worker` container's own environment or the real Azure resource.

## Real failure mode already found (not hypothetical)

Small/general-purpose vision models frequently **ignore** the "respond
only with JSON" instruction and describe the image conversationally
instead (confirmed live with `moondream`). This is expected, not a bug —
`_parse_json_response` rejects it and `execute_analysis` resolves the
traite to `Écarts à traiter` with the real error in `audit_log`
(`analyse_echouee`) and the **full raw response** in the `extractions_ia`
table (`app/services/extraction_log.py` — raw SQL via `psycopg`, not the
ORM). If a traite seems stuck instead of resolving to that status after a
failed extraction, that's a real regression — check
`app/services/traite_processing.py`'s `except Exception` handling around
the extraction call first.

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
