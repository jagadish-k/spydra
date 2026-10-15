// The BFF application, separate from the listener so tooling can build it
// without a port (scripts/export-openapi.ts, ADR-0013's no-listener export).
// What is final here: TypeBox as the schema layer, the OpenAPI document, and
// the healthz convention — liveness only, dependencies reported, never
// allowed to fail the route (same contract as the api's healthz).

import { Type, type Static } from "@sinclair/typebox";
import swagger from "@fastify/swagger";
import swaggerUi from "@fastify/swagger-ui";
import Fastify, { type FastifyInstance } from "fastify";
import postgres from "postgres";

const CRAWLER_API_BASE = process.env.CRAWLER_API_BASE ?? "http://api:8000";

const HealthResponse = Type.Object({
  status: Type.Literal("ok"),
  db: Type.Union([Type.Literal("ok"), Type.Literal("down")]),
  api: Type.Union([Type.Literal("ok"), Type.Literal("down")]),
});
type HealthResponse = Static<typeof HealthResponse>;

export async function buildApp(): Promise<FastifyInstance> {
  // spec 010 §4: bff health reports {db, api}. postgres.js is the app's db
  // driver (ADR-0021) — max 1 connection, the health check needs no pool.
  // Created per app: no connection is opened until a query runs, so
  // building the app (tests, OpenAPI export) touches no database.
  const db = postgres(
    process.env.DATABASE_URL ?? "postgres://spydra_bff:spydra@db:5432/spydra",
    { max: 1, connect_timeout: 2, idle_timeout: 5 },
  );

  async function dbUp(): Promise<boolean> {
    try {
      await db`select 1`;
      return true;
    } catch {
      // Unreachable or slow — "down". Liveness must not depend on the db.
      return false;
    }
  }

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
  app.addHook("onClose", async () => {
    await db.end();
  });

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
      db: (await dbUp()) ? "ok" : "down",
      api: (await crawlerApiUp()) ? "ok" : "down",
    }),
  );

  // The swagger plugin serves its JSON at /docs/json; DEVELOPMENT.md's
  // table promises /openapi.json, so expose the spec there too.
  app.get("/openapi.json", { schema: { hide: true } }, async () =>
    app.swagger(),
  );

  return app;
}
