.PHONY: dev test lint migrate build docs docs-build

# Start the full local stack (db, redis, backend in Docker; frontend with hot reload)
dev:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose up db redis backend -d && \
	cd frontend && npm run dev

# Run all backend tests inside Docker
test:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose run --rm backend python -m pytest -q

# Run ruff linter on backend and ESLint on frontend
lint:
	ruff check backend/
	cd frontend && npm run lint

# Apply the latest SQL migration manually on the running DB container
migrate:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker exec phaemos-db-1 psql -U postgres -d phaemos \
		-f /docker-entrypoint-initdb.d/001_initial_schema.sql

# Build the Next.js frontend for production
build:
	cd frontend && npm run build

# Serve the MkDocs documentation site locally with hot reload
docs:
	pip install -r requirements-docs.txt -q && mkdocs serve

# Build the MkDocs site into site/ (output is gitignored; Vercel runs this at deploy time)
docs-build:
	pip install -r requirements-docs.txt -q && mkdocs build

# Seed the database with demo data (useful after docker compose down wipes the volume)
seed:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose run --rm backend python -c "from app.db import Base, engine; Base.metadata.create_all(engine)"
