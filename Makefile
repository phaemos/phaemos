.PHONY: dev test lint migrate build docs docs-build

# start the full local stack (db, redis, backend in Docker; frontend with hot reload)
dev:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose up db redis backend -d && \
	cd frontend && npm run dev

# run all backend tests inside Docker
test:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose run --rm backend python -m pytest -q

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

# seed the database with demo data (useful after docker compose down wipes the volume)
seed:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose run --rm backend python -c "from app.db import Base, engine; Base.metadata.create_all(engine)"
