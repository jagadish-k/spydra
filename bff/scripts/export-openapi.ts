// Export the BFF's OpenAPI document to stdout — ADR-0013's mechanism: build
// the app inside the container, no listener, no published port. The Makefile
// redirects stdout to frontend/src/api/openapi.ui.json (gitignored scratch);
// openapi-typescript turns it into schema.ui.d.ts in the web container.
import { buildApp } from "../src/app.js";

const app = await buildApp();
await app.ready();
process.stdout.write(`${JSON.stringify(app.swagger(), null, 2)}\n`);
await app.close();
