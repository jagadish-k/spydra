# Spydra render sidecar — the ONLY image in the stack with a browser
# (ADR-0016). The base tag and the playwright pin in render/package.json MUST
# move together: npm driver ≠ image browsers is the mismatch that costs a day
# (DEVELOPMENT.md § Playwright lives in the sidecar only). Never run
# `playwright install` at container start — the browsers are already here.
FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /app
COPY render/package.json ./
RUN npm install
COPY render/src src
COPY render/tests tests

# Spec 012: POST /render + GET /healthz on :3001. The browser launches at
# boot; if it cannot, the process exits and the healthcheck goes unhealthy.
EXPOSE 3001
CMD ["node", "src/index.js"]
