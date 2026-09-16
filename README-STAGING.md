# Staging deployment with Docker

Run these commands in Bash on the staging server, from the project root:

```bash
cd /var/www/apps/TRAIT-AI-APP
```

## 1. Check prerequisites

- Install Docker Engine and the Docker Compose plugin.
- Deploy the project source, including `back/scripts/create_database.py`.
- Provide your server's `docker-compose.staging.yml`. This file is deployment-specific and is not included in this checkout. Commands below assume it defines a service named `backend` with `/app` as its working directory, using `back/Dockerfile`.
- Have a reachable PostgreSQL server and an existing PostgreSQL login role. The creation script creates a database, not the PostgreSQL server or login role.

```bash
docker --version
docker compose version
test -f docker-compose.staging.yml
```

## 2. Configure staging

Keep your existing staging `.env`. If this is a new setup, create it from the example without overwriting an existing file:

```bash
test -f .env || cp .env.example .env
nano .env
```

Ensure the staging Compose file passes the following settings into the backend container, either through `environment:` or `env_file:`. A root `.env` provides Compose interpolation values; it does not automatically inject every variable into containers.

| Backend setting | Staging value |
| --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://APP_USER:URL_ENCODED_PASSWORD@DB_HOST:5432/trait_ai` |
| `ENVIRONMENT` | `production` for the staging deployment |
| `JWT_SECRET` | A private random value replacing the development default |
| `OCR_PROVIDER` | `stub` for simulated extraction, or `azure_openai` for real extraction |
| `CORS_ALLOWED_ORIGINS` | Your frontend origin if frontend and API use different origins |

Use the PostgreSQL hostname reachable **from inside the backend container**. For a shared Docker database, both containers need access to the same Docker network. `localhost` inside the backend points to the backend container itself.

If Compose constructs `DATABASE_URL` from `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`, configure those values instead. URL-encode special characters in credentials used in a connection URL. Leave `ALEMBIC_DATABASE_URL` unset for normal staging setup so database creation, migrations, and the application use the same database.

For real OCR, also pass `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_API_VERSION` into the backend. Use the values for your Azure deployment.

Validate Compose configuration without printing resolved secrets:

```bash
docker compose -f docker-compose.staging.yml config --quiet
```

## 3. Build and start containers

```bash
docker compose -f docker-compose.staging.yml up -d --build
docker compose -f docker-compose.staging.yml ps
```

The existing backend Dockerfile includes `scripts/` in both development and production images. Rebuild after deploying the new creation script.

Container startup alone does not run database creation or migrations. Keep staging unavailable to users until the following initialization steps finish.

## 4. Create the application database

```bash
docker compose -f docker-compose.staging.yml exec backend python -m scripts.create_database
```

The script uses the configured database URL, connects to the existing maintenance database `postgres` on the same server with the same credentials, and creates the target database if it is missing. The connecting role owns the new database. If the database already exists, the script leaves it unchanged. It does not create tables or users.

The database role needs permission to connect to the maintenance database and `CREATEDB` permission (or equivalent administrator privileges) when creation is needed. If it lacks these permissions, ask the PostgreSQL administrator to create the target database owned by the application role, then continue with migrations.

If your server uses a different maintenance database:

```bash
docker compose -f docker-compose.staging.yml exec backend python -m scripts.create_database --maintenance-db template1
```

Run initialization once at a time. Continue only after each command succeeds.

## 5. Create tables and apply migrations

```bash
docker compose -f docker-compose.staging.yml exec backend alembic upgrade head
docker compose -f docker-compose.staging.yml exec backend alembic current
```

Alembic applies pending migrations, including application tables, the `imx` schema, and the `pgcrypto` extension. The role must have the necessary schema and extension permissions. Existing applied migrations are not repeated.

## 6. Create the first login account

Replace the example password before running:

```bash
docker compose -f docker-compose.staging.yml exec backend python -m scripts.create_user mc-user 'REPLACE_WITH_STAGING_PASSWORD'
```

This creates `mc-user`. Running it again for the same username resets that account's password. The password argument can be recorded in shell history.

## 7. Optional: add demo IMX records

Use this only if staging should contain the project's demo reference data:

```bash
docker compose -f docker-compose.staging.yml exec backend python -m scripts.seed
```

Seeding inserts or updates the predefined demo adherent, debtor, and invoice records. It does not create login accounts or traites. Skip it when staging uses real reference data.

## 8. Verify the deployment

```bash
docker compose -f docker-compose.staging.yml ps
docker compose -f docker-compose.staging.yml logs --tail=100 backend
docker compose -f docker-compose.staging.yml exec backend curl --fail http://localhost:8000/api/health
docker compose -f docker-compose.staging.yml exec backend alembic current
```

The health endpoint should return `status: ok`. It checks database connectivity; successful migrations and an actual login are also needed to verify the setup. Open your configured staging frontend URL, log in with the account from step 6, and check that the application loads. The public URL and port depend on your staging Compose file and reverse proxy.

## Later deployments

Back up the staging database before applying new migrations. During a maintenance window:

```bash
docker compose -f docker-compose.staging.yml up -d --build
docker compose -f docker-compose.staging.yml exec backend alembic upgrade head
docker compose -f docker-compose.staging.yml exec backend alembic current
docker compose -f docker-compose.staging.yml exec backend curl --fail http://localhost:8000/api/health
```

Database creation and account creation are not required on every deployment. Re-run seeding only when you intend to update demo records.

## Stop or inspect the stack

```bash
docker compose -f docker-compose.staging.yml logs -f backend
docker compose -f docker-compose.staging.yml down
docker compose -f docker-compose.staging.yml up -d
```

`down` preserves named volumes; do not add `--volumes` if you need to retain their data. An external PostgreSQL server has its own persistence and backup configuration. Ensure uploaded files are stored in a persistent volume in your staging Compose file.

## Troubleshooting

| Error | Action |
| --- | --- |
| `database "trait_ai" does not exist` | Run step 4, then step 5. Alembic needs an existing database. |
| `No module named scripts.create_database` | Deploy the script and rebuild the backend image with step 3. Check that custom Docker builds include `scripts/`. |
| `permission denied to create database` | Have the PostgreSQL administrator create the database owned by the application role. |
| Cannot connect to maintenance database | Verify that `postgres` exists and is accessible, or use `--maintenance-db` with an accessible existing database. |
| Connection refused or hostname cannot be resolved | Check PostgreSQL availability, hostname, port, firewall, and Docker network membership. |
| Password authentication failed | Correct the database credentials passed into the backend, then recreate it with `up -d --force-recreate backend`. |
| Relation/table does not exist | Run migrations and ensure the application and Alembic target the same database. |
| Permission denied creating schemas or extensions | Ask the database administrator to provide the required permissions or provision the extension. |
| Login fails after seeding | Create the login account with step 6; seeding does not provision users. |
