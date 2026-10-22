// The sidecar refuses requests that come from a browser (ADR-0038).
//
// `render` shares `render-link` with the worker, and the browser it drives
// runs in the same container, so a crawled page can reach this server at
// `render:3001` or `127.0.0.1:3001`. Network position cannot tell the two
// clients apart; request shape can. Chromium attaches headers a page can
// neither remove nor forge (they are forbidden header names), and the
// worker's httpx client sends none of them:
//
//   - `Origin` on every POST, same-origin or not, and on every CORS request;
//   - `Sec-Fetch-Site`, `-Dest`, `-User` to trustworthy origins (localhost);
//   - `Upgrade-Insecure-Requests` on every navigation. A page that navigates
//     itself to `http://render:3001/healthz` sends no `Origin` and, on plain
//     http to a non-loopback host, no `Sec-Fetch-*`; without this header the
//     sidecar answered and its state became the crawled page (2.0 review).
//
// What is still served to a page: an opaque subresource GET (`<img
// src=…/healthz>`). It carries none of these, and the page cannot read the
// response. No such request can start a render: every POST carries `Origin`.
//
// `Sec-Fetch-Mode` is NOT on the list: Node's own fetch sends it (measured:
// `sec-fetch-mode: cors`), and the healthcheck and the acceptance suite are
// Node clients.
//
// `POST /render` also demands `content-type: application/json`, which turns
// away a page's "simple" (`text/plain`, form) POST with a 415. It is NOT a
// barrier on its own: the sidecar intercepts every request with
// `context.route('**/*')`, and under that Chromium sends a page's CORS JSON
// POST without a preflight (measured in 2.0's tests: 2 renders with the header
// list emptied). On `render:3001`, plain http to a non-loopback host, Chromium
// sends no `Sec-Fetch-*` either, so `Origin` is the check that holds there.
// Do not remove it on the strength of the content-type check.

const BROWSER_HEADERS = [
  'origin',
  'sec-fetch-site',
  'sec-fetch-dest',
  'sec-fetch-user',
  'upgrade-insecure-requests',
];

/**
 * Why this request is refused, or null if it may proceed.
 * @param {import('node:http').IncomingMessage} req
 * @returns {{ status: number, error: string } | null}
 */
export function refusal(req) {
  const browserHeader = BROWSER_HEADERS.find((name) => req.headers[name] !== undefined);
  if (browserHeader) {
    return { status: 403, error: `refused: ${browserHeader} header — browser requests are not served` };
  }
  if (req.method === 'POST' && req.url === '/render' && !isJson(req.headers['content-type'])) {
    return { status: 415, error: 'POST /render requires content-type: application/json' };
  }
  return null;
}

/** @param {string | undefined} contentType */
function isJson(contentType) {
  return (contentType ?? '').split(';')[0].trim().toLowerCase() === 'application/json';
}
