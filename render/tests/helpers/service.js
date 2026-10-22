// Harness for the spec 012 §6 acceptance suite (BUILD_PLAN 1.5).
//
// Two processes per case, both started here and both killed here:
//
//   1. 1.4's fixture site, run from the read-only /fixtures mount. It is
//      1.4's OWN stdlib server, not a Node reimplementation — a second copy
//      of the route table is the drift the single-source JSON-LD twins exist
//      to prevent, and `backend/tests/test_fixture_site.py` is what keeps
//      the shapes honest. `render` shares no network with api (ADR-0038), so the
//      api container's fixture server is unreachable by design; this one
//      binds the render container's own loopback.
//
//   2. The sidecar itself, as a child process with per-case env. A case that
//      needs a 2-page recycle threshold and a case that needs a 1 s queue
//      window cannot share an instance without each one's settings making
//      the other's assertions meaningless, so every case gets its own port.
//
// Readiness is polled, never slept for: a fixed sleep is either slower than
// it needs to be or flaky, and both show up as "the browser is unreliable".

import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:http';

const FIXTURE_ROOT = process.env.FIXTURE_ROOT ?? '/fixtures';
const READY_TIMEOUT_MS = 30_000;

/** An OS-assigned free port, so two cases never collide on a fixed one.
 *
 *  The probe is closed before the port is handed over, which leaves a small
 *  window in which something else could take it. Accepted: the alternative
 *  is passing a listening socket into a child process, and a failure here is
 *  a loud EADDRINUSE at startup rather than a silent wrong result. If this
 *  ever flakes, the fix is a retry around startSidecar, not a fixed port. */
async function freePort() {
  const probe = createServer();
  probe.listen(0, '127.0.0.1');
  await once(probe, 'listening');
  const { port } = probe.address();
  await new Promise((resolve) => probe.close(resolve));
  return port;
}

/**
 * Poll `check` until it resolves truthy, or throw after READY_TIMEOUT_MS.
 * @param {() => Promise<boolean>} check
 * @param {string} what named in the failure, so a timeout says which process
 */
async function waitUntil(check, what) {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  for (;;) {
    try {
      if (await check()) return;
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) throw new Error(`${what} did not become ready in ${READY_TIMEOUT_MS}ms`);
    await new Promise((r) => setTimeout(r, 100));
  }
}

/** @param {import('node:child_process').ChildProcess} child */
function stopper(child) {
  return async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.kill('SIGTERM');
    const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
    await once(child, 'exit').catch(() => {});
    clearTimeout(timer);
  };
}

/** 1.4's fixture site on this container's loopback. */
export async function startFixtureSite() {
  const port = await freePort();
  const child = spawn('python3', ['server.py'], {
    cwd: FIXTURE_ROOT,
    env: { ...process.env, FIXTURE_PORT: String(port), FIXTURE_HOST: '127.0.0.1' },
    stdio: ['ignore', 'ignore', 'inherit'],
  });
  const baseUrl = `http://127.0.0.1:${port}`;
  const stop = stopper(child);
  try {
    await waitUntil(async () => (await fetch(`${baseUrl}/robots.txt`)).ok, 'fixture site');
  } catch (e) {
    await stop();
    throw e;
  }
  return { baseUrl, stop };
}

/**
 * The sidecar, with per-case env. Defaults are deliberately NOT set here:
 * an unset knob must show spec behaviour, so only what a case overrides is
 * passed.
 *
 * @param {Record<string, string>} [env]
 */
export async function startSidecar(env = {}) {
  const port = await freePort();
  const child = spawn('node', ['src/index.js'], {
    cwd: '/app',
    env: { ...process.env, ...env, RENDER_PORT: String(port) },
    stdio: ['ignore', 'ignore', 'inherit'],
  });
  const baseUrl = `http://127.0.0.1:${port}`;
  const stop = stopper(child);
  try {
    await waitUntil(async () => (await healthz(baseUrl)).ok === true, 'render sidecar');
  } catch (e) {
    // A readiness timeout used to throw before the caller could register the
    // child for teardown, leaking a Node process and a Chromium for the rest
    // of the run — and on this image that is the expensive kind of leak.
    await stop();
    throw e;
  }
  return { baseUrl, stop };
}

/** @param {string} baseUrl */
export async function healthz(baseUrl) {
  const res = await fetch(`${baseUrl}/healthz`);
  return res.json();
}

/**
 * POST /render. Returns the status alongside the body because half the
 * criteria are about the status code (503, 200-with-truncation).
 *
 * @param {string} baseUrl
 * @param {Record<string, unknown>} body
 */
export async function render(baseUrl, body) {
  const res = await fetch(`${baseUrl}/render`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await res.json() };
}

/** The raw HTTP response, for the half of §6's first criterion that is about
 *  what the browser ADDED. Rendered content proves nothing on its own. */
export async function raw(url) {
  const res = await fetch(url);
  return res.text();
}
