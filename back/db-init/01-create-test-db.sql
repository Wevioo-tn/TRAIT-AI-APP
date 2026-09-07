-- Runs once, on first container startup, alongside the main POSTGRES_DB.
-- Gives the automated test suite its own database so tests never touch dev
-- or seeded data. Idempotent via \gexec so re-running the container against
-- an existing volume never fails.
SELECT 'CREATE DATABASE trait_ai_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'trait_ai_test')
\gexec
