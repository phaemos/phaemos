# build from the repository root, because the changelog pages read CHANGELOG.md, which sits one folder above frontend/:
#   docker build -f frontend/Dockerfile -t phaemos-frontend .
# infra/docker-compose.yml does this. Frontend/Dockerfile.dockerignore keeps the rest of the monorepo out of the context.
FROM node:24-alpine AS base
WORKDIR /app

FROM base AS deps
COPY frontend/package.json frontend/package-lock.json* ./frontend/
WORKDIR /app/frontend
# every dependency is installed here, the build tools included. NODE_ENV is set later, in the builder stage.
RUN npm ci

FROM base AS builder
WORKDIR /app/frontend
COPY --from=deps /app/frontend/node_modules ./node_modules
COPY frontend/ ./
COPY CHANGELOG.md /app/CHANGELOG.md
# the browser bundle reads the API's address at build time. There is no default: a build must be told where the API is and a production
# build refuses an address that is not https (next.config.mjs), so a bare `docker build` stops with a message and never ships a bundle
# that points visitors at http://localhost:8000. A real image passes --build-arg NEXT_PUBLIC_API_URL=https://api.example.com.
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# a local stack that really is http says so with --build-arg ALLOW_INSECURE_API_URL=1. It is off unless asked for.
ARG ALLOW_INSECURE_API_URL=
ENV ALLOW_INSECURE_API_URL=$ALLOW_INSECURE_API_URL
# a production build stops while a legal page still holds a placeholder (scripts/check-legal.mjs reads NODE_ENV). To try the
# image before the pages are finished, pass --build-arg LEGAL_PLACEHOLDERS=allow.
ARG LEGAL_PLACEHOLDERS=
ENV LEGAL_PLACEHOLDERS=$LEGAL_PLACEHOLDERS
ENV NODE_ENV=production
RUN npm run build

FROM base AS runner
ENV NODE_ENV=production
WORKDIR /app
# the lockfile is in frontend/ only, so the standalone output is rooted there and server.js is at its top
COPY --from=builder --chown=node:node /app/frontend/.next/standalone ./
COPY --from=builder --chown=node:node /app/frontend/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/frontend/public ./public

# the server holds no secret and needs no privilege: it runs as the unprivileged user the base image provides
USER node
EXPOSE 3000
CMD ["node", "server.js"]
