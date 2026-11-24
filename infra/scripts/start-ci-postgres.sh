#!/usr/bin/env bash
# starts a throwaway PostgreSQL 15 container for a CI job and waits until it accepts
# connections. The image is pulled on its own so a transient registry timeout can be retried:
# a service container starts before any step and cannot be retried.
#
#   bash infra/scripts/start-ci-postgres.sh [container-name] [database-name]
#
# defaults: container `postgres`, database `phaemos_test`. The password is a fixed throwaway
# value for a container that only exists for the run and listens on the runner's loopback
# address.
set -euo pipefail

# the image is named by digest as well as tag. The tag says what we meant and the digest says what we
# get, so a moved tag cannot change the database a job runs. To refresh it:
# docker buildx imagetools inspect postgres:15
IMAGE="postgres:15@sha256:8cf673eb99f8b9042c9078ee4ca0e775428c77097e9d999bfc9ba4b4347f5733"

name="${1:-postgres}"
database="${2:-phaemos_test}"

for attempt in 1 2 3 4 5; do
    docker pull "${IMAGE}" && break
    echo "pull attempt ${attempt} failed, retrying in 15s..."
    sleep 15
done

docker run -d \
    --name "${name}" \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=password \
    -e "POSTGRES_DB=${database}" \
    -p 127.0.0.1:5432:5432 \
    "${IMAGE}" > /dev/null

tries=0
until docker exec "${name}" pg_isready -h 127.0.0.1 -U postgres -q; do
    tries=$((tries + 1))
    if [ "${tries}" -ge 60 ]; then
        echo "the database did not become ready" >&2
        exit 1
    fi
    sleep 1
done
echo "${name} is ready"
