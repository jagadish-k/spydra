// BFF health skeleton (BUILD_PLAN 0.9). The real routes — schedules,
// saved views, /overview — arrive in phase 3 (spec 011). What is final
// here: TypeBox as the schema layer, the OpenAPI document, and the
// healthz convention — liveness only, dependencies reported, never
// allowed to fail the route (same contract as the api's healthz).

import { Type, type Static } from "@sinclair/typebox";
import swagger from "@fastify/swagger";
import swaggerUi from "@fastify/swagger-ui";
import Fastify from "fastify";

const CRAWLER_API_BASE = process.env.CRAWLER_API_BASE ?? "http://api:8000";

// spec 010 §4: bff health reports {db, api}. The db check arrives with
// task 0.10 — drizzle brings the driver.
const HealthResponse = Type.Object({
  status: Type.Literal("ok"),
  api: Type.Union([Type.Literal("ok"), Type.Literal("down")]),
});
type HealthResponse = Static<typeof HealthResponse>;

async function crawlerApiUp(): Promise<boolean> {
  try {
    const res = await fetch(`${CRAWLER_API_BASE}/api/crawler/healthz`, {
      signal: AbortSignal.timeout(2_000),
    });
    return res.ok;
  } catch {
    // Unreachable, slow, or 5xx — all mean "down". Liveness must not
    // depend on the api being up.
    return false;
  }
}

const app = Fastify({ logger: true });

await app.register(swagger, {
  openapi: {
    info: {
      title: "Spydra BFF",
      description: "Scheduling, saved views and aggregation for the UI",
      version: "0.1.0",
    },
  },
});
await app.register(swaggerUi, { routePrefix: "/docs" });

app.get(
  "/api/ui/healthz",
  { schema: { response: { 200: HealthResponse } } },
  async (): Promise<HealthResponse> => ({
    status: "ok",
    api: (await crawlerApiUp()) ? "ok" : "down",
  }),
);

// The swagger plugin serves its JSON at /docs/json; DEVELOPMENT.md's
// table promises /openapi.json, so expose the spec there too.
app.get("/openapi.json", { schema: { hide: true } }, async () => app.swagger());

const port = Number(process.env.PORT ?? 3000);
await app.listen({ port, host: "0.0.0.0" });
