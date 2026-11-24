# the base image is pinned by digest as well as tag, so a changed or poisoned tag cannot reach
# the build. To refresh it: docker buildx imagetools inspect python:3.12-slim prints the current
# digest. Put it here, build and release it as a signed tag (docs/deployment.md, Section 6)
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# the webhook address check relies on the ipaddress module's is_global tables as fixed in
# Python 3.12.4 (6to4 and several reserved ranges were wrong before). The 3.12-slim tag follows
# the latest patch and this line stops a build on an older cached base.
RUN python -c "import sys; assert sys.version_info >= (3, 12, 4), sys.version"

WORKDIR /app

# the production image installs requirements.lock, which pins every package and every
# indirect package with hashes, with --require-hashes. The development compose file passes
# REQUIREMENTS=requirements-dev.txt, which adds the test and plotting packages for `make test`
# and is installed without hashes. Refresh the lock with infra/scripts/lock-requirements.sh
# after any change to requirements.txt
ARG REQUIREMENTS=requirements.lock
COPY requirements.txt requirements.lock requirements-dev.txt ./
RUN if [ "${REQUIREMENTS}" = "requirements.lock" ]; then \
        pip install --no-cache-dir --require-hashes -r requirements.lock; \
    else \
        pip install --no-cache-dir -r "${REQUIREMENTS}"; \
    fi

# the API runs as an unprivileged user. The folders it writes to (uploaded firmware and the trained model) are
# created here and owned by that user, so a new named volume mounted over them starts with the right owner. A
# volume that already exists keeps its old owner: see "Run the API as an unprivileged user" in docs/deployment.md
RUN useradd --system --uid 10001 --user-group --no-create-home phaemos \
 && mkdir -p /var/lib/phaemos/firmware /var/lib/phaemos/model /app/firmware_uploads /app/ml \
 && chown -R phaemos:phaemos /var/lib/phaemos /app/firmware_uploads /app/ml

COPY --chown=phaemos:phaemos . .

USER phaemos

EXPOSE 8000

# uvicorn flags, each checked against the pinned uvicorn's own option list:
#   --no-access-log             stops the request line of ordinary requests. It does NOT stop the
#                               connection line uvicorn writes for a live socket. app/logging_config.py
#                               filters query strings out of that line, which is what keeps a token
#                               in a socket address out of the container log.
#   --no-server-header          stops the Server: uvicorn header, which tells a stranger what is running.
#   --ws-max-size 8192          a socket client never needs to send more than the 4096 character auth
#                               frame, so a bigger message is refused before it is read into memory
#                               (the default is 16 MB a message).
#   --ws-per-message-deflate false
#                               a compressed frame can expand about 1000 times, so 15 MB cost the sender
#                               a few kilobytes. Dashboard sockets do not need compression.
#   --limit-concurrency 150     past this many open connections and running requests uvicorn answers 503
#                               instead of taking more. The container is capped at 384 MB and the database
#                               pool holds 15 connections, so roughly 100 idle sockets (small) plus 50
#                               requests in flight is what fits. The app also caps sockets per account and
#                               per address.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header", "--ws-max-size", "8192", "--ws-per-message-deflate", "false", "--limit-concurrency", "150", "--no-proxy-headers"]
