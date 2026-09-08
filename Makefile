.PHONY: up down build logs migrate seed test test-front typecheck-front lint

up:
	docker compose up

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

migrate:
	docker compose run --rm backend alembic upgrade head

seed:
	docker compose run --rm backend python -m scripts.seed

test:
	docker compose run --rm backend pytest

test-front:
	docker compose run --rm frontend npx vitest run

typecheck-front:
	docker compose run --rm frontend npx tsc -b

lint:
	docker compose run --rm backend ruff check .
