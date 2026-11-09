.PHONY: dev-all down-all apply-migrations docker-up docker-down docker-logs

dev-all:
	docker compose up --build -d

down-all:
	docker compose down

apply-migrations:
	uv run alembic upgrade head

docker-up: dev-all

docker-down: down-all

docker-logs:
	docker compose logs -f api
