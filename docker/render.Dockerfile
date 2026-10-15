# Spydra render sidecar — the ONLY image in the stack with a browser
# (ADR-0016). The base tag and the playwright pin in render/package.json MUST
# move together: npm driver ≠ image browsers is the mismatch that costs a day
# (DEVELOPMENT.md § Playwright lives in the sidecar only). Never run
# `playwright install` at container start — the browsers are already here.
FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /app
COPY render/package.json ./
RUN npm install

# Placeholder until task 0.11 builds the real service (POST /render +
# GET /healthz). Keeps the container up so `docker compose ps` is honest; the
# /healthz probe fails until then, which nothing depends_on (ADR-0016).
CMD ["node", "-e", "console.log('render placeholder — task 0.11'); setInterval(() => {}, 1e9)"]
