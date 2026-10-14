.PHONY: up down logs bootstrap sync ask test lint eval k8s-build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f worker api

bootstrap:
	docker compose run --rm worker bootstrap

sync:
	docker compose run --rm worker sync

ask:
	docker compose exec api goszakup ask "$(Q)"

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src scripts migrations tests

eval:
	cd backend && uv run goszakup eval run

k8s-build:
	kubectl kustomize deploy/k8s/base
