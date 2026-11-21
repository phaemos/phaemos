.PHONY: dev test lint migrate build docs docs-build

# start the full local stack (db, redis, backend in Docker; frontend with hot reload).
# Dependencies are installed on the first run so a fresh clone starts without extra steps.
dev:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose up db redis backend -d && \
	cd frontend && { [ -d node_modules ] || npm ci; } && npm run dev

# run all backend tests inside Docker against a separate phaemos_test database,
# created on first use. The suite drops its tables at the end, so it must never
# share a database with the development data. The wait checks the TCP port
# because a first-run server answers on its socket before it accepts connections
# from other containers. It gives up after a minute rather than loop for ever.
test:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose up db redis -d && \
	tries=0 && until docker compose exec -T db pg_isready -h 127.0.0.1 -U postgres -q; do \
		tries=$$((tries + 1)); \
		if [ $$tries -ge 60 ]; then echo "database did not become ready" >&2; exit 1; fi; \
		sleep 1; \
	done && \
	{ docker compose exec -T db psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'phaemos_test'" | grep -q 1 \
		|| docker compose exec -T db psql -U postgres -c "CREATE DATABASE phaemos_test"; } && \
	docker compose run --rm -e DATABASE_URL=postgresql://postgres:password@db:5432/phaemos_test backend python -m pytest -q

# run ruff linter on backend and ESLint on frontend
lint:
	ruff check backend/
	cd frontend && npm run lint

# apply every SQL migration in order to the running DB container. Each file is
# guarded with IF NOT EXISTS, so re-running is safe.
migrate:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	for f in backend/migrations/*.sql; do \
		echo "applying $$f"; \
		docker exec -i phaemos-db-1 psql -v ON_ERROR_STOP=1 -U postgres -d phaemos < "$$f" || exit 1; \
	done

# build the Next.js frontend for production
build:
	cd frontend && npm run build

# serve the MkDocs documentation site locally with hot reload
docs:
	pip install -r requirements-docs.txt -q && mkdocs serve

# build the MkDocs site into site/ (output is gitignored; Vercel runs this at deploy time)
docs-build:
	pip install -r requirements-docs.txt -q && mkdocs build

# seed the database with demo data (useful after docker compose down -v wipes the volume)
seed:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose run --rm backend python -c "from app.db import Base, engine; Base.metadata.create_all(engine)"
