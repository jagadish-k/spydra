# Spydra BFF — Fastify on Node 26, pinned by major.minor (ADR-0017).
# `npm ci` at build time bakes node_modules into the image so the
# bff_modules named volume seeds from it on first run — the ./bff bind at
# /app would otherwise leave the volume empty (ADR-0010).
FROM node:26-slim

WORKDIR /app
# Makefile targets exec tools directly (compose run bff tsc), not via npm
# scripts — so node_modules/.bin must be on PATH.
ENV PATH="/app/node_modules/.bin:$PATH"
COPY bff/package.json bff/package-lock.json ./
RUN npm ci

# Dev entrypoint; compose overrides with `npm run dev`.
CMD ["npm", "run", "dev"]
