# Spydra web — Vite dev server on Node 26, pinned by major.minor (ADR-0017).
# The real frontend (and vite.config.ts, with the polling macOS bind mounts
# need) arrives with task 0.12; until then compose's command starts vite,
# which serves an empty root. node_modules baked here seeds the web_modules
# named volume on first run (ADR-0010).
FROM node:26-slim

WORKDIR /app
# Tools exec'd directly (compose run web tsc — from BUILD_PLAN 0.12 on) need
# node_modules/.bin on PATH; npm scripts would provide it themselves.
ENV PATH="/app/node_modules/.bin:$PATH"
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Inert on purpose — the dev server is compose's `npm run dev -- --host 0.0.0.0`.
CMD ["node", "-e", "console.log('web: dev server runs via the compose command')"]
