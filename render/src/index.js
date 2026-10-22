// Spydra render sidecar — spec 012. Plain ESM JavaScript on purpose: this is
// infrastructure, not an app package; node:http + playwright is the whole
// stack (no express, no build step).
//
// The sidecar does not retry and does not back off (spec 012 §1) — politeness
// lives in the scheduler. It renders one page or fails.

import http from 'node:http';
import { chromium } from 'playwright';
import { MAX_BODY_BYTES, truncateHtml } from './limits.js';
import { validateRequest } from './validate.js';
import { ContextQueue } from './context-queue.js';
import { refusal } from './guard.js';

// 3001 is the port the worker reaches over `render-link` (ADR-0038).
// Env-readable only so the acceptance suite can run two instances side by
// side with different recycle and queue settings.
const PORT = intEnv('RENDER_PORT', 3001);
const CONTEXTS_MAX = intEnv('RENDER_CONTEXTS', 3);
const RECYCLE_AFTER_PAGES = intEnv('RECYCLE_AFTER_PAGES', 500);
// Spec 012 §2: beyond the cap a request queues for 5 s, then 503s. Env-
// readable so the acceptance suite can observe the 503 without a 5 s wait
// per case; intEnv falls back to the spec value, so an unset or junk env
// cannot weaken it.
const QUEUE_WAIT_MS = intEnv('RENDER_QUEUE_WAIT_MS', 5000);
const RECYCLE_AFTER_MS = 30 * 60 * 1000; // spec 012 §2: 500 pages OR 30 min

/** @param {string} name @param {number} fallback */
function intEnv(name, fallback) {
  const n = Number.parseInt(process.env[name] ?? '', 10);
  return Number.isInteger(n) && n > 0 ? n : fallback;
}

// ---------------------------------------------------------------------------
// Browser pool: ONE browser, a context per request, recycled by age/use.
// Recycling only happens between requests, so in-flight contexts drain on
// the old browser before it closes (spec 012 §2).
// ---------------------------------------------------------------------------

class BrowserPool {
  constructor() {
    /** @type {{ browser: import('playwright').Browser, refs: number, retired: boolean } | null} */
    this._active = null;
    this.pagesSinceRestart = 0;
    this._startedAt = 0;
  }

  /** Launch if there is no active browser (boot, or after a recycle). */
  async ensure() {
    if (!this._active) {
      const browser = await chromium.launch({
        args: ['--disable-dev-shm-usage'], // spec 012 §2, belt to compose's shm_size
      });
      this._active = { browser, refs: 0, retired: false };
      this.pagesSinceRestart = 0;
      this._startedAt = Date.now();
    }
    return this._active;
  }

  /**
   * Take a reference to the active browser, retiring it first if it is due.
   * The caller must release() exactly once.
   */
  async acquire() {
    if (this._active && !this._active.retired) {
      const due =
        this.pagesSinceRestart >= RECYCLE_AFTER_PAGES || Date.now() - this._startedAt >= RECYCLE_AFTER_MS;
      if (due) this._retireActive();
    }
    const entry = await this.ensure();
    entry.refs++;
    return entry;
  }

  release(entry) {
    entry.refs--;
    if (entry.retired && entry.refs === 0) entry.browser.close().catch(() => {});
  }

  /** Count a completed render against the recycle threshold. */
  notePage() {
    this.pagesSinceRestart++;
  }

  version() {
    return this._active ? this._active.browser.version() : '';
  }

  /** Detach the current browser; it closes once its last context finishes. */
  _retireActive() {
    const old = this._active;
    if (!old) return;
    old.retired = true;
    this._active = null;
    if (old.refs === 0) old.browser.close().catch(() => {});
  }

  /** Close everything (SIGTERM). Draining contexts get a dead browser, which
   *  is correct at shutdown — compose has already sent them SIGTERM too. */
  async closeAll() {
    if (this._active) {
      await this._active.browser.close().catch(() => {});
      this._active = null;
    }
  }
}

const pool = new BrowserPool();
const queue = new ContextQueue(CONTEXTS_MAX, QUEUE_WAIT_MS);

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/** Map a Playwright failure to the spec 012 §1 status table. */
function classify(e) {
  if (e instanceof Error && e.name === 'TimeoutError') {
    return { status: 504, body: { error: 'render timed out' } };
  }
  return { status: 502, body: { error: `navigation failed: ${e instanceof Error ? e.message : String(e)}` } };
}

/**
 * @param {import('./validate.js').RenderRequest} req
 * @returns {Promise<{ status: number, body: unknown }>}
 */
async function render(req) {
  const blocked = new Set(req.block_resources);
  let entry = null;
  let context = null;
  try {
    entry = await pool.acquire();
    context = await entry.browser.newContext({
      userAgent: req.user_agent,
      extraHTTPHeaders: req.extra_headers,
      acceptDownloads: false, // spec 012 §3
      // Permissions: nothing is ever granted via grantPermissions(), so
      // geolocation/camera/mic/notifications are denied by default.
    });
    await context.route('**/*', (route) => {
      if (blocked.has(route.request().resourceType())) route.abort().catch(() => {});
      else route.continue().catch(() => {});
    });

    const page = await context.newPage();
    page.on('dialog', (d) => d.dismiss().catch(() => {})); // never block on alert()
    let consoleErrors = 0;
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors++;
    });

    const t0 = Date.now();
    let response = null;
    try {
      response = await page.goto(req.url, { waitUntil: req.wait_until, timeout: req.timeout_ms });
    } catch (e) {
      return classify(e);
    }
    const t1 = Date.now();

    // wait_for_selector takes precedence (spec 012 §1) and spends only the
    // REMAINING budget, so navigate+settle can never exceed the 30 s ceiling.
    if (req.wait_for_selector !== undefined) {
      const remaining = Math.max(1, req.timeout_ms - (t1 - t0));
      try {
        await page.waitForSelector(req.wait_for_selector, { timeout: remaining });
      } catch (e) {
        return classify(e);
      }
    }
    const t2 = Date.now();

    const { html, truncated } = truncateHtml(await page.content());
    pool.notePage();
    return {
      status: 200,
      body: {
        html,
        status: response ? response.status() : 0,
        final_url: page.url(),
        timing_ms: { navigate: t1 - t0, settle: t2 - t1, total: t2 - t0 },
        console_errors: consoleErrors,
        ...(truncated ? { truncated: true } : {}), // spec 012 §3: truncate and flag
      },
    };
  } catch (e) {
    // Browser-launch or context-creation failure (bad extra_headers etc.) —
    // not a navigation problem, so not one of the table codes.
    return { status: 500, body: { error: `render failed: ${e instanceof Error ? e.message : String(e)}` } };
  } finally {
    if (context) await context.close().catch(() => {});
    if (entry) pool.release(entry); // entry only exists once a slot is held
    queue.release();
  }
}

// ---------------------------------------------------------------------------
// HTTP — two routes, hand-rolled. The 64 KB body cap is enforced while
// reading, before anything is parsed (spec 012 §3).
// ---------------------------------------------------------------------------

/** @param {http.ServerResponse} res @param {number} status @param {unknown} body */
function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) });
  res.end(payload);
}

/** @param {http.IncomingMessage} req @returns {Promise<Buffer>} rejects with {status, error} */
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let rejected = false;
    req.on('data', (chunk) => {
      if (rejected) return; // don't buffer past a refused body
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        // Stop consuming rather than destroying the socket: the client gets
        // its 413, and node closes the connection after flushing (request
        // incomplete ⇒ connection: close).
        rejected = true;
        req.pause();
        reject({ status: 413, error: 'request body exceeds 64 KB' });
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', () => reject({ status: 400, error: 'request read failed' }));
  });
}

const server = http.createServer((req, res) => {
  // Before routing and before the body is read: a refused request costs a
  // header lookup, never a browser context (ADR-0038).
  const refused = refusal(req);
  if (refused) {
    json(res, refused.status, { error: refused.error });
    return;
  }

  if (req.method === 'GET' && req.url === '/healthz') {
    pool
      .ensure()
      .then(() =>
        json(res, 200, {
          ok: true,
          contexts_in_use: queue.inUse,
          contexts_max: queue.max,
          pages_since_restart: pool.pagesSinceRestart,
          browser_version: pool.version(),
        }),
      )
      .catch((e) => json(res, 500, { ok: false, error: `browser unavailable: ${e?.message ?? e}` }));
    return;
  }

  if (req.method === 'POST' && req.url === '/render') {
    readBody(req)
      .then((buf) => {
        let parsed;
        try {
          parsed = JSON.parse(buf.toString('utf8'));
        } catch {
          return { status: 400, body: { error: 'body is not valid JSON' } };
        }
        const v = validateRequest(parsed);
        if (!v.ok) return { status: 422, body: { error: v.error } };
        // The queue slot is held for the whole render — that is the cap.
        return queue
          .acquire()
          .then(() => render(v.value))
          .catch(() => ({ status: 503, body: { error: `no context available within ${QUEUE_WAIT_MS}ms` } }));
      })
      .then((r) => {
        if (!res.destroyed) json(res, r.status, r.body);
      })
      .catch((r) => {
        if (!res.destroyed) json(res, r.status ?? 500, r.body ?? { error: r.error ?? 'internal error' });
      });
    return;
  }

  json(res, 404, { error: 'not found' });
});

pool
  .ensure()
  .then(() => {
    server.listen(PORT, () => console.log(`render sidecar on :${PORT} — ${pool.version()}`));
  })
  .catch((e) => {
    console.error(`browser launch failed, refusing to start: ${e?.message ?? e}`);
    process.exit(1);
  });

process.on('SIGTERM', () => {
  server.close();
  pool.closeAll().finally(() => process.exit(0));
});
