// Spec 012 §6 acceptance — BUILD_PLAN 1.5.
//
// Six of §6's ten criteria: the ones a real browser can prove against 1.4's
// fixture site. The other four, and the phase that covers each, are in
// `.tasks/feat-1.5-render-acceptance.md`.
//
// Everything here goes through POST /render against a sidecar started as a
// child process. There is no mocking library and no patched clock: the two
// timing criteria are settled on observed elapsed time, which is the only
// kind of evidence that would have caught the defects this suite exists for.
//
// Each criterion has been mutation-tested — the guard in `src/` broken on
// purpose, the test confirmed red, the guard restored. The matrix is in the
// task file, and THREE of the six were green against a broken service on the
// first attempt. A guard whose test stays green when the guard is broken is
// not covered, and this is the service where that is cheapest to get wrong.
//
// Each case gets its own sidecar, started in `before` and stopped in
// `after`. Sharing one would mean a 2-page recycle threshold and a 1 s queue
// window interfering with each other's assertions; leaving them running
// would mean A3 measuring render times with other Chromium instances
// resident, which is how a timing test ends up quarantined (TESTING.md §5).

import assert from 'node:assert/strict';
import { once } from 'node:events';
import http from 'node:http';
import { after, before, describe, test } from 'node:test';
import { MAX_HTML_BYTES } from '../src/limits.js';
import { healthz, raw, render, startFixtureSite, startSidecar } from './helpers/service.js';

const JS_PAGE = '/katalog/stirnlochschluessel-30-80';
const DIALOG_PAGE = '/katalog/drehmomentschluessel-20-100';
const GALLERY = '/catalog/abrasives/discs/rfd-115-060/galerie';

let site;

before(async () => {
  site = await startFixtureSite();
});

after(async () => {
  if (site) await site.stop();
});

/** Markup with <script> elements removed.
 *
 *  A fixture that writes its product from a JS string literal carries the
 *  product's class names in its own source. Comparing raw against rendered
 *  without stripping scripts compares a page to itself. */
function withoutScripts(html) {
  return html.replace(/<script[\s\S]*?<\/script>/g, '');
}

/** Poll until `check` is true. Never a fixed sleep: where sequencing is the
 *  test (A5), a sleep is the wrong instrument. */
async function until(check, what, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 50));
  }
}

/** A sidecar scoped to one describe block. */
function sidecarFor(env) {
  const box = {};
  before(async () => {
    box.svc = await startSidecar(env);
  });
  after(async () => {
    if (box.svc) await box.svc.stop();
  });
  return box;
}

// ---------------------------------------------------------------------------

describe('A1 — a JS-dependent page renders content the raw response does not have', () => {
  const box = sidecarFor();

  test('the product is present after render and absent before it', async () => {
    const url = `${site.baseUrl}${JS_PAGE}`;

    const rawHtml = await raw(url);
    const rendered = await render(box.svc.baseUrl, { url, wait_until: 'networkidle' });

    assert.equal(rendered.status, 200);

    // BOTH sides are compared with <script> stripped, and that symmetry is
    // the test. The fixture writes the product from a JS string literal, so
    // `produkt__preis` appears in the page SOURCE as well as in the rendered
    // DOM — an assertion over the raw markup is satisfied by a script that
    // was never run. Found by mutation: returning the navigation response
    // body instead of `page.content()` left this case green.
    const renderedDom = withoutScripts(rendered.body.html);
    assert.match(renderedDom, /class="produkt__preis"/, 'the browser did not run the fixture script');
    assert.match(renderedDom, /24,90\s*EUR/);

    // The second half is the half that is easy to lose. Asserting only that
    // the rendered HTML has the product would pass against a page that was
    // never dynamic, and so against a sidecar that had quietly stopped using
    // a browser at all.
    assert.doesNotMatch(
      withoutScripts(rawHtml),
      /produkt__preis/,
      'the fixture serves the product without JavaScript, so this proves nothing',
    );
    assert.equal(rendered.body.final_url, url);
    assert.equal(rendered.body.status, 200);
  });
});

describe('A2 — the fourth concurrent request queues and 503s', () => {
  // A 1 s window instead of the spec's 5 s: the behaviour under test is
  // "queues, then refuses", and five seconds of it buys nothing. The default
  // stays 5 s in compose and in index.js, so forgetting to set this shows
  // spec behaviour rather than test behaviour.
  const box = sidecarFor({ RENDER_CONTEXTS: '3', RENDER_QUEUE_WAIT_MS: '1000' });

  test('three contexts are held, a fourth 503s, and no fourth context opens', async () => {
    const slow = `${site.baseUrl}/slow/5000`;
    const inFlight = [0, 1, 2].map(() =>
      render(box.svc.baseUrl, { url: slow, wait_until: 'load', timeout_ms: 20_000 }),
    );

    // Wait for the cap to actually be reached rather than assuming three
    // POSTs means three contexts.
    await until(
      async () => (await healthz(box.svc.baseUrl)).contexts_in_use === 3,
      'the three slow renders to reach the cap',
    );
    const h = await healthz(box.svc.baseUrl);
    assert.equal(h.contexts_in_use, 3);
    assert.equal(h.contexts_max, 3);

    const fourth = await render(box.svc.baseUrl, {
      url: slow,
      wait_until: 'load',
      timeout_ms: 20_000,
    });

    assert.equal(fourth.status, 503, 'the fourth request was served instead of refused');
    assert.match(fourth.body.error, /no context available/);

    // "rather than opening a fourth context" is the criterion, and the 503
    // alone does not prove it. This reads the queue's own counter, so it
    // cannot see a context opened outside the queue — what it does catch is
    // the cap being raised or removed, which is the mutation it was checked
    // against. `/inspect` sharing the cap is 6.1's criterion, not this one.
    const during = await healthz(box.svc.baseUrl);
    assert.ok(
      during.contexts_in_use <= 3,
      `contexts_in_use reached ${during.contexts_in_use}, so the cap is not a cap`,
    );

    for (const r of await Promise.all(inFlight)) assert.equal(r.status, 200);
  });
});

describe('A3 — block_resources measurably reduces render time', () => {
  const box = sidecarFor();

  test('a 24-image gallery renders faster with images blocked', async () => {
    const url = `${site.baseUrl}${GALLERY}`;
    const req = { url, wait_until: 'networkidle', timeout_ms: 25_000 };

    // Warm-up, discarded. Without it the first newContext's cost lands
    // entirely in the `unblocked` number and the comparison is biased toward
    // passing — a broken route.abort() would still show a saving.
    await render(box.svc.baseUrl, { ...req, block_resources: [] });

    const unblocked = await render(box.svc.baseUrl, { ...req, block_resources: [] });
    const blocked = await render(box.svc.baseUrl, {
      ...req,
      block_resources: ['image', 'font', 'media'],
    });

    assert.equal(unblocked.status, 200);
    assert.equal(blocked.status, 200);

    // The arithmetic, so this is not a bare `<`. The gallery has 24 images,
    // each served behind a 150 ms delay (fixtures/server.py
    // SLOW_IMAGE_DELAY_S), and Chromium opens about six connections per
    // host: roughly four waves, so ~600 ms of the unblocked render is images
    // alone. The floor is half that, leaving 2x headroom for a loaded box
    // while staying far outside the noise between two renders of one page.
    const saved = unblocked.body.timing_ms.total - blocked.body.timing_ms.total;
    assert.ok(
      saved >= 300,
      `blocking images saved only ${saved}ms (unblocked ${unblocked.body.timing_ms.total}ms, ` +
        `blocked ${blocked.body.timing_ms.total}ms) — spec 012 §2 claims it typically halves render time`,
    );

    // ...and blocking must not have cost the content. A "faster" render that
    // lost the product would satisfy the timing assertion and break the
    // service.
    assert.match(blocked.body.html, /produkt__preis/);
  });
});

describe('A4 — a page opening alert() does not hang the request', () => {
  const box = sidecarFor();

  test('the dialogs are dismissed and the post-dialog DOM comes back', async () => {
    const url = `${site.baseUrl}${DIALOG_PAGE}`;
    const result = await render(box.svc.baseUrl, {
      url,
      wait_until: 'networkidle',
      timeout_ms: 8000,
    });

    assert.equal(result.status, 200, 'the request did not survive the dialog');

    // The fixture opens alert(), confirm() and prompt() BEFORE it writes the
    // product, so this is what distinguishes "dismissed" from "blocked until
    // the timeout". Without it a sidecar that hung would still return 200
    // with an empty shell.
    //
    // Note which guard this actually covers: DELETING the dismissal in
    // src/index.js leaves this green, because Playwright auto-dismisses when
    // no listener is attached. The mutation that bites is a listener that
    // dismisses nothing — which is also the real regression, since anyone
    // adding `page.on('dialog', …)` for logging would start hanging every
    // page that opens one.
    assert.match(result.body.html, /produkt__preis/, 'the page never got past its dialog');
    assert.ok(
      result.body.timing_ms.total < 5000,
      `took ${result.body.timing_ms.total}ms, which is the shape of a dialog waiting out the timeout`,
    );
  });
});

describe('A5 — the browser recycles past its page threshold without dropping an in-flight render', () => {
  const box = sidecarFor({ RECYCLE_AFTER_PAGES: '2', RENDER_CONTEXTS: '3' });

  test('a render in flight across a recycle survives it, and the counter resets', async () => {
    const fast = `${site.baseUrl}${JS_PAGE}`;

    // The ORDER here is the test, and the obvious order is wrong. With the
    // threshold already reached, the slow render is itself what trips the
    // recycle: `acquire()` retires the browser BEFORE taking a reference
    // (src/index.js), so the slow render runs on the FRESH browser and
    // nothing is ever in flight across a restart. Written that way, this
    // case stayed green with the drain removed outright — a recycle that
    // kills a live render, the one thing the criterion forbids.
    //
    // So: reach the threshold only once the slow render already holds a
    // reference, and let a LATER request be the one that trips it.

    // 1 of 2.
    assert.equal((await render(box.svc.baseUrl, { url: fast, wait_until: 'load' })).status, 200);

    // In flight, holding a reference to the browser that is about to retire.
    const inFlight = render(box.svc.baseUrl, {
      url: `${site.baseUrl}/slow/4000`,
      wait_until: 'load',
      timeout_ms: 20_000,
    });
    await until(
      async () => (await healthz(box.svc.baseUrl)).contexts_in_use === 1,
      'the slow render to take a context',
    );

    // 2 of 2 — the threshold is now reached, but no acquire has seen it yet.
    assert.equal((await render(box.svc.baseUrl, { url: fast, wait_until: 'load' })).status, 200);
    assert.equal(
      (await healthz(box.svc.baseUrl)).pages_since_restart,
      2,
      'the threshold was not reached',
    );

    // This request trips the recycle while the slow render is still open on
    // the old browser. The old browser must stay alive until that render
    // finishes — `release()` closes a retired browser only once its last
    // reference goes, and that branch is what this case exists to reach.
    assert.equal((await render(box.svc.baseUrl, { url: fast, wait_until: 'load' })).status, 200);

    // 1 on a fresh browser; 3 if no recycle happened.
    const mid = await healthz(box.svc.baseUrl);
    assert.ok(
      mid.pages_since_restart < 3,
      `pages_since_restart is ${mid.pages_since_restart}, so no recycle happened`,
    );

    // The assertion with the teeth. A drain that closed the old browser on
    // retirement leaves this render talking to a dead browser, and it comes
    // back 5xx rather than 200.
    const drained = await inFlight;
    assert.equal(drained.status, 200, 'the in-flight render was dropped by the recycle');
    assert.match(withoutScripts(drained.body.html), /produkt__preis/);
  });
});

describe('A6 — an oversized response is truncated and flagged', () => {
  const box = sidecarFor();

  test('20 MB comes back capped at MAX_HTML_BYTES with truncated: true', async () => {
    const result = await render(box.svc.baseUrl, {
      url: `${site.baseUrl}/oversized/20`,
      wait_until: 'load',
      timeout_ms: 30_000,
    });

    assert.equal(result.status, 200);
    assert.equal(result.body.truncated, true, 'a 20 MB response was not flagged');
    assert.equal(
      Buffer.byteLength(result.body.html, 'utf8'),
      MAX_HTML_BYTES,
      'the response was not cut at the spec 012 §3 cap',
    );
  });
});

describe('boundary regression guard — not one of the six criteria', () => {
  test('no internal service name resolves from inside the render container', async () => {
    // §6's network-isolation criterion ("a page fetching http://api:8000/…
    // cannot reach it") needs the full stack and so is deferred — see the
    // task file. But its NEGATIVE half costs nothing here and nothing needs
    // to be running: `render` shares no network with these services
    // (ADR-0023, ADR-0038), so their names must not resolve. Without this,
    // an `extra_hosts:` line or a shared network added later reopens "the
    // only real isolation boundary in the stack" silently.
    //
    // `worker` is deliberately NOT on the list. Since ADR-0038 it shares
    // `render-link` with `render` and resolves by design; it listens on
    // nothing, and the sidecar's own guard (below) is what stops a page
    // using `render-link` the other way.
    const dns = await import('node:dns');
    for (const host of ['api', 'db', 'bff', 'edge', 'web']) {
      await assert.rejects(
        () => dns.promises.lookup(host),
        `${host} resolves from the render container, so the egress isolation in ADR-0023/0038 is gone`,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// ADR-0038: the browser shares this container, so a crawled page can reach
// the sidecar's own API. The sidecar refuses requests shaped like a browser's.
// ---------------------------------------------------------------------------

/** One raw HTTP request with exactly these headers. node:http rather than
 *  fetch, because fetch adds headers of its own (`sec-fetch-mode`) and the
 *  guard is about which headers are present. Resolves on the response: a
 *  refusal that does not read the body may reset the socket while a large
 *  body is still being written, and that is the guard working. */
function send(baseUrl, { method, path, headers = {}, body }) {
  return new Promise((resolve, reject) => {
    let answered = false;
    const req = http.request(`${baseUrl}${path}`, { method, headers }, (res) => {
      answered = true;
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let json = null;
        try {
          json = JSON.parse(text);
        } catch {
          // not JSON; the status is the assertion
        }
        resolve({ status: res.statusCode, json });
      });
    });
    req.on('error', (e) => {
      if (!answered) reject(e);
    });
    if (body !== undefined) req.write(body);
    req.end();
  });
}

/** A loopback HTTP server owned by the test. `handler` returns
 *  `{ status, headers, body }`; every request is recorded. */
async function startServer(handler, host = '127.0.0.1') {
  const seen = [];
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const entry = { method: req.method, url: req.url, headers: req.headers };
      seen.push(entry);
      const out = handler(entry, Buffer.concat(chunks).toString('utf8'));
      res.writeHead(out.status ?? 200, out.headers ?? {});
      res.end(out.body ?? '');
    });
  });
  server.listen(0, host);
  await once(server, 'listening');
  const baseUrl = `http://${host}:${server.address().port}`;
  return {
    baseUrl,
    seen,
    stop: () => new Promise((resolve) => server.close(resolve)),
  };
}

/** A page whose script tries every way a page can POST to a URL, against
 *  each target: the real sidecar, and a decoy that accepts anything. The
 *  decoy is the control. If its count is right, the script ran and sent
 *  every request, so the real sidecar's refusal is the only reason the
 *  marker was never rendered. Without it, a page whose script never ran
 *  would pass this test against a sidecar with no guard at all. */
function attackerPage({ targets, marker }) {
  const payload = JSON.stringify({ url: marker, wait_until: 'load' });
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>attacker</title></head>
<body>
${Object.keys(targets).map((name) => `<iframe name="sink-${name}"></iframe>`).join('')}
<script>
const PAYLOAD = ${JSON.stringify(payload)};
const TARGETS = ${JSON.stringify(targets)};
const tries = [
  // A "simple" request: no preflight, so the POST itself is sent.
  (b) => fetch(b + '/render', { method: 'POST', mode: 'no-cors', headers: { 'content-type': 'text/plain' }, body: PAYLOAD }),
  // The worker's own content type: preflighted.
  (b) => fetch(b + '/render', { method: 'POST', headers: { 'content-type': 'application/json' }, body: PAYLOAD }),
  // No type set at all: text/plain;charset=UTF-8, simple.
  (b) => fetch(b + '/render', { method: 'POST', mode: 'no-cors', body: PAYLOAD }),
  (b) => new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('POST', b + '/render');
    x.setRequestHeader('content-type', 'application/json');
    x.onload = resolve; x.onerror = reject;
    x.send(PAYLOAD);
  }),
  (b) => Promise.resolve(navigator.sendBeacon(b + '/render', PAYLOAD)),
];
function formPost(name, b) {
  return new Promise((resolve) => {
    const frame = document.querySelector('iframe[name="sink-' + name + '"]');
    frame.addEventListener('load', resolve, { once: true });
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = b + '/render';
    form.enctype = 'text/plain';
    form.target = 'sink-' + name;
    const input = document.createElement('input');
    // text/plain form encoding is name=value, so the JSON is split across
    // the two to come out whole: {"url":...,"x":"="}
    input.name = PAYLOAD.slice(0, -1) + ',"x":"';
    input.value = '"}';
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
  });
}
(async () => {
  for (const [name, b] of Object.entries(TARGETS)) {
    await Promise.allSettled(tries.map((t) => t(b)));
    await formPost(name, b);
  }
  const done = document.createElement('p');
  done.id = 'done';
  done.textContent = 'done'; // visible, or wait_for_selector never sees it
  document.body.appendChild(done);
})();
</script>
</body></html>`;
}

// Requests per target the attacker page sends: five scripted, one form.
const ATTEMPTS = 6;

/** This container's own address, on a network rather than loopback. */
async function ownAddress() {
  const dns = await import('node:dns');
  const os = await import('node:os');
  return (await dns.promises.lookup(os.hostname(), { family: 4 })).address;
}

describe('ADR-0038 — the sidecar refuses requests shaped like a browser', () => {
  const box = sidecarFor();
  let page; // the attacker page and the marker, one origin
  // Two ways in, each with its decoy. Loopback is `127.0.0.1:3001`, where
  // Chromium adds Sec-Fetch-*. The container's own address stands in for
  // `render:3001` on `render-link`: plain http to a non-loopback host is not
  // a trustworthy origin, so Chromium sends no Sec-Fetch-* there, and the
  // guard has Origin alone to go on.
  let decoy;
  let decoyLan;
  let targets;
  const markerHits = (tag) => page.seen.filter((r) => r.url === `/marker/${tag}`).length;
  const markerUrl = (tag) => `${page.baseUrl}/marker/${tag}`;
  const renderBody = (tag) => JSON.stringify({ url: markerUrl(tag), wait_until: 'load' });

  before(async () => {
    page = await startServer((req) => {
      if (req.url.startsWith('/marker/')) {
        return { headers: { 'content-type': 'text/html' }, body: '<p>marker</p>' };
      }
      if (req.url === '/attacker') {
        return {
          headers: { 'content-type': 'text/html' },
          body: attackerPage({ targets, marker: markerUrl('page') }),
        };
      }
      return { status: 404 };
    });
    const permissive = (req) => ({
      status: req.method === 'OPTIONS' ? 204 : 200,
      headers: {
        'access-control-allow-origin': '*',
        'access-control-allow-methods': 'POST',
        'access-control-allow-headers': 'content-type',
        'content-type': 'application/json',
      },
      body: req.method === 'OPTIONS' ? '' : '{}',
    });
    const lan = await ownAddress();
    decoy = await startServer(permissive);
    decoyLan = await startServer(permissive, lan);
    targets = {
      sidecar: box.svc.baseUrl,
      'sidecar-lan': box.svc.baseUrl.replace('127.0.0.1', lan),
      decoy: decoy.baseUrl,
      'decoy-lan': decoyLan.baseUrl,
    };
  });

  after(async () => {
    if (page) await page.stop();
    if (decoy) await decoy.stop();
    if (decoyLan) await decoyLan.stop();
  });

  test('control: a worker-shaped POST /render is served, and the marker counts it', async () => {
    // Without this, "the marker was never hit" below could mean the marker
    // cannot be hit at all.
    const r = await send(box.svc.baseUrl, {
      method: 'POST',
      path: '/render',
      headers: { 'content-type': 'application/json' },
      body: renderBody('control'),
    });
    assert.equal(r.status, 200);
    assert.equal(markerHits('control'), 1);
  });

  for (const [name, value] of [
    ['origin', 'http://127.0.0.1:1'],
    ['sec-fetch-site', 'same-site'],
    ['sec-fetch-dest', 'empty'],
    ['sec-fetch-user', '?1'],
  ]) {
    test(`a request carrying ${name} is refused with 403 and renders nothing`, async () => {
      const tag = `header-${name}`;
      const r = await send(box.svc.baseUrl, {
        method: 'POST',
        path: '/render',
        headers: { 'content-type': 'application/json', [name]: value },
        body: renderBody(tag),
      });
      assert.equal(r.status, 403);
      const h = await send(box.svc.baseUrl, { method: 'GET', path: '/healthz', headers: { [name]: value } });
      assert.equal(h.status, 403, 'every path is guarded, not only /render');
      assert.equal(markerHits(tag), 0);
    });
  }

  for (const type of [undefined, 'text/plain', 'application/x-www-form-urlencoded']) {
    test(`POST /render with content-type ${type ?? '(none)'} is refused with 415`, async () => {
      const tag = `type-${type ?? 'none'}`.replace(/\W/g, '-');
      const r = await send(box.svc.baseUrl, {
        method: 'POST',
        path: '/render',
        headers: type === undefined ? {} : { 'content-type': type },
        body: renderBody(tag),
      });
      assert.equal(r.status, 415);
      assert.equal(markerHits(tag), 0);
    });
  }

  test('the refusal comes before the body is read', async () => {
    // Past the 64 KB cap: a guard that ran after reading would answer 413.
    const big = 'x'.repeat(100 * 1024);
    const browser = await send(box.svc.baseUrl, {
      method: 'POST',
      path: '/render',
      headers: { 'content-type': 'application/json', origin: 'http://127.0.0.1:1' },
      body: big,
    });
    assert.equal(browser.status, 403);
    const plain = await send(box.svc.baseUrl, {
      method: 'POST',
      path: '/render',
      headers: { 'content-type': 'text/plain' },
      body: big,
    });
    assert.equal(plain.status, 415);
  });

  test("Node's fetch, which sends only sec-fetch-mode, is still served", async () => {
    // The healthcheck in compose and this suite's own helpers are Node
    // clients. Refusing sec-fetch-mode would take the sidecar out of its
    // own healthcheck.
    const viaFetch = await fetch(`${box.svc.baseUrl}/healthz`);
    assert.equal(viaFetch.status, 200);
    const explicit = await send(box.svc.baseUrl, {
      method: 'GET',
      path: '/healthz',
      headers: { 'sec-fetch-mode': 'cors' },
    });
    assert.equal(explicit.status, 200);
  });

  test('a page whose script POSTs to the sidecar does not cause a second render', async () => {
    const rendersBefore = (await healthz(box.svc.baseUrl)).pages_since_restart;

    const r = await render(box.svc.baseUrl, {
      url: `${page.baseUrl}/attacker`,
      wait_until: 'networkidle',
      wait_for_selector: '#done',
      timeout_ms: 20_000,
    });
    assert.equal(r.status, 200, JSON.stringify(r.body).slice(0, 300));

    // The control half: every attempt reached both decoys, so the script
    // ran and the requests left the page. Chromium put Origin on every one
    // of them, which is the premise the guard rests on (on the LAN path it
    // is the ONLY browser header there is).
    for (const [name, d] of [['loopback', decoy], ['lan', decoyLan]]) {
      const posts = () => d.seen.filter((q) => q.method === 'POST');
      await until(
        async () => posts().length >= ATTEMPTS,
        `the ${name} decoy to receive ${ATTEMPTS} POSTs (got ${posts().length})`,
        10_000,
      );
      assert.equal(posts().length, ATTEMPTS, name);
      assert.deepEqual(
        posts().filter((q) => q.headers.origin === undefined),
        [],
        `a browser POST to the ${name} decoy arrived without Origin, so the guard would not see it`,
      );
    }

    // The sidecar half: nothing the page sent became a render. Polled for a
    // while rather than read once, because a render the page caused would
    // run concurrently and could finish after ours.
    const settleBy = Date.now() + 2_000;
    while (Date.now() < settleBy) {
      assert.equal(markerHits('page'), 0, 'a page made the sidecar render on its behalf');
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const h = await healthz(box.svc.baseUrl);
    assert.equal(h.pages_since_restart, rendersBefore + 1, 'only the attacker page itself was rendered');
    assert.equal(h.contexts_in_use, 0);
  });
});
