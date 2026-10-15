// BFF entrypoint (compose: npm run dev → tsx watch src/server.ts). The app
// itself is built in app.ts so tooling (scripts/export-openapi.ts, the
// ADR-0013 export path) can construct it without a listener.
import { buildApp } from "./app.js";

const port = Number(process.env.PORT ?? 3000);
const app = await buildApp();
await app.listen({ port, host: "0.0.0.0" });
