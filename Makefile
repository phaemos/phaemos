.PHONY: dev dev-key test lint migrate build docs docs-build docs-check sim-nano sim-blackpill firmware-check ml-eval openapi workflows-check

# start the full local stack (db, redis, backend in Docker; frontend with hot reload);
# dependencies are installed on the first run so a fresh clone starts without extra steps.
dev: infra/.env.dev
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose up db redis backend -d && \
	cd frontend && { [ -d node_modules ] || npm ci; } && npm run dev

# the development signing key. It is made once from the system's random source into an ignored
# file that the development compose file reads. It is reused on every later run and is never in
# the repository. Delete the file to get a new key (every development session then ends).
infra/.env.dev:
	umask 077 && printf 'SECRET_KEY=%s\n' "$$(openssl rand -hex 32)" > $@

dev-key: infra/.env.dev

# run all backend tests inside Docker against a separate phaemos_test database,
# created on first use. The suite drops its tables at the end, so it must never
# share a database with the development data. The wait checks the TCP port
# because a first-run server answers on its socket before it accepts connections
# from other containers. It gives up after a minute rather than loop for ever.
test: infra/.env.dev
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

# apply every SQL migration that has not been applied yet, in order, to the running DB container and
# record each one. It is the same script deploy.sh runs (infra/scripts/migrate.sh), so the two cannot
# drift apart. A file that was applied and has since been edited stops it: see the script's header.
migrate:
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	bash infra/scripts/migrate.sh dev

# build the Next.js frontend for production
build:
	cd frontend && npm run build

# serve the MkDocs documentation site locally with hot reload
docs:
	pip install -r requirements-docs.txt -q && mkdocs serve

# build the MkDocs site into site/ (output is gitignored; Vercel runs this at deploy time)
docs-build:
	pip install -r requirements-docs.txt -q && mkdocs build

# build the docs strictly into a scratch folder and check the built site in a browser (contrast, targets, focus, reflow, requests).
# run `make openapi` first: two pages link to the files it writes. Needs a Chromium that Playwright can find (see docs/README.md).
docs-check:
	pip install --require-hashes -r requirements-docs.txt -r requirements-docs-check.txt -q
	d=$$(mktemp -d) && mkdocs build --strict -d $$d/site && python3 docs/overrides/check_site.py --site $$d/site --out $$d/check && echo "report in $$d/check"

# seed the database with demo data (useful after docker compose down -v wipes the volume)
seed: infra/.env.dev
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose run --rm backend python -c "from app.db import Base, engine; Base.metadata.create_all(engine)"

# write docs/openapi.json and docs/api-routes.md from the code. Needs no database and no server, only the backend's Python
# packages (pip install -r backend/requirements-dev.txt). CI runs it and fails when the committed copies are out of date
openapi:
	cd backend && python3 -m app.scripts.export_openapi ../docs/openapi.json ../docs/api-routes.md

# build the Nano node firmware and run it on a simulated ATmega328P (simavr) against a simulated
# BME280 and analogue inputs. Needs PlatformIO and simavr, see firmware/arduino_nano/sim/README.md.
# the run exits non-zero if any scenario fails.
sim-nano:
	$(MAKE) -C firmware/arduino_nano/sim run

sim-blackpill:
	$(MAKE) -C firmware/stm32_blackpill/sim run

# build every firmware environment (the hub's two, the Nano's four and the Black Pill's one) and
# run every host test under firmware/esp32/test_host and firmware/stm32_blackpill/test_host. each
# test is built and run with the command in its own file header, so a header that rots is caught
# here. it stops at the first failure. the hub's tests need ArduinoJson, which the first hub
# build downloads, so the builds run first. needs PlatformIO and a C and C++ compiler. nothing
# here runs on a board: see firmware/README.md. the two emulations stay separate (sim-nano and
# sim-blackpill).
firmware-check:
	set -e; \
	pio run -d firmware/esp32 -e esp32dev -e esp32dev_revb; \
	pio run -d firmware/arduino_nano/nano_node -e nanoatmega328 -e nanoatmega328new -e nanoatmega328new_wdt -e nanoatmega328new_cal; \
	pio run -d firmware/stm32_blackpill; \
	TMPDIR=$${TMPDIR:-/tmp}; export TMPDIR; \
	for dir in firmware/esp32/test_host firmware/stm32_blackpill/test_host; do \
		for f in $$dir/*.c $$dir/*.cpp; do \
			[ -f "$$f" ] || continue; \
			grep -E '^[ /*]*(cc|c\+\+) .* -o "\$$\{TMPDIR' "$$f" | sed -E 's/^[ \/*]+//' | while IFS= read -r cmd; do \
				echo "== $$f"; \
				(cd $$dir && sh -c "$$cmd") || exit 1; \
			done || exit 1; \
		done; \
	done; \
	echo "firmware-check passed"

# measure the anomaly model on simulated machines: false alerts per machine per week and injected faults caught, the
# old rule beside the new one. It needs no database. Simulated data only: it has not seen a real machine
ml-eval: infra/.env.dev
	export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH" && \
	docker compose run --rm -T backend python -m app.scripts.evaluate_model

# lint the workflows and check that every action is pinned to a full commit. The same two checks run in the CI job `workflows`.
# needs actionlint and shellcheck on the PATH
workflows-check:
	actionlint
	bash infra/scripts/check-action-pins.sh
