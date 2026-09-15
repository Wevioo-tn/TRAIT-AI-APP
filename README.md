# TRAIT-AI

Bill-of-exchange processing with React, FastAPI, PostgreSQL, and Azure OpenAI vision.

## Docker quick start

Requires Docker Desktop and an initialized application database. The current
Docker startup does not create application tables on a fresh PostgreSQL volume.
Commands below run from the project root in PowerShell.

Create `.env` from `.env.example` if you do not already have one:

```powershell
Copy-Item .env.example .env
```

Configure extraction in `.env`:

```dotenv
OCR_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com
AZURE_OPENAI_API_KEY=YOUR-KEY
AZURE_OPENAI_DEPLOYMENT=YOUR-VISION-DEPLOYMENT
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

The deployment must support images and strict JSON-schema output.
Use `OCR_PROVIDER=stub` for local development without real OCR or provider calls.

```powershell
docker compose up -d --build
```

For local demo IMX records, run after the tables exist:

```powershell
docker compose exec backend python -m scripts.seed
```

Seeding creates no traites and does not create or reset users. It populates
demo IMX records; use it only for local development. Existing traites remain
until explicitly cleared.

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/health
- Configured account: `mc-user` (use the separately supplied password).
  Seeding does not provision this account on a fresh database.

URLs use the default ports; adjust them if your `.env` overrides the ports.
After changing Azure settings:

```powershell
docker compose up -d --force-recreate backend
docker compose logs -f backend
```

Stop the stack without deleting database volumes:

```powershell
docker compose down
```

## Backend with a Python virtual environment

Requires Python 3.12 and an initialized PostgreSQL database. Start only PostgreSQL
in Docker when running the backend locally. Stop any Docker backend first to
avoid a port conflict.

```powershell
docker compose stop backend
docker compose up -d postgres
py -3.12 -m venv back/.venv
.\back\.venv\Scripts\python.exe -m pip install -r back/requirements-dev.txt
$env:PYTHONPATH = "$PWD/back"
$env:DATABASE_URL = "postgresql+psycopg://trait:trait@localhost:5432/trait_ai"
$env:UPLOAD_DIR = "$PWD/back/uploads"
.\back\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Run from the root so the backend reads the root `.env`. Adjust the database URL
for your PostgreSQL credentials and published port. In another terminal, start
the frontend locally (Node.js 20+):

```powershell
cd front
npm ci
npm run dev
```

## Clear traite data only

This permanently empties `public.traites` and its dependent tables, including
extracted fields, document records, matches, verifications, decisions, and audit
logs. **IMX records, login users, and table definitions are preserved.** Uploaded
files remain on disk. Stop analysis before clearing to avoid concurrent writes.

From CMD or PowerShell at the project root:

```powershell
docker compose stop backend
powershell -NoProfile -ExecutionPolicy Bypass -File .\clear-db.ps1
docker compose start backend
```

For a backend running in a virtual environment, stop it with Ctrl+C before
clearing and restart it afterward. PostgreSQL must remain running in Docker.

The script executes:

```sql
TRUNCATE TABLE public.traites RESTART IDENTITY CASCADE;
```

For non-default database names or users:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\clear-db.ps1 -Database my_database -DatabaseUser my_user
```

## OCR/extraction: a real VLM, chosen at deploy time

A VLM (vision-language model) reads document images and returns structured data.
`OCR_PROVIDER` selects the extractor; `AZURE_OPENAI_DEPLOYMENT` selects the model.

1. Upload the recto and verso and launch analysis. FastAPI runs it in a background task.
2. The backend validates JPEG/PNG/WebP images, applies orientation, flattens
   transparency onto white, and sends normalized JPEG images with high detail to Azure.
3. The model transcribes printed and handwritten text using source-zone mapping
   and a strict JSON schema. Dates and leading zeroes are preserved; unreadable
   values remain null. Occurrences represent distinct document zones, not photos.
4. The server builds the second RIB from the four structured component readings.
   The existing backend JSON keys and paired component fields remain compatible.
5. Results are saved, checked for consistency, and matched against IMX. Existing
   checks can flag missing or different occurrences even when a reading is correct.

The implementation follows `ai-generated-ocr` with the backend output contract;
it runs inside the backend and does not call that standalone service. Extraction
attempts and raw responses are logged in `extractions_ia`. Invalid or incomplete
responses fail analysis and send the traite for review. PDF extraction is not
implemented. Six signature/cachet presence flags are extracted and exposed in
`visual_marks`; the issuer-signature mention shows detection while awaiting
manual verification. Detection never substitutes for manual approval. Older
documents need a new analysis to populate these flags.

Automated tests validate the pipeline with simulated provider responses. Actual
handwriting accuracy must be evaluated using real scans and the configured deployment.
