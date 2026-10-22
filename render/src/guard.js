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
//   - `Sec-Fetch-Site`, `-Dest`, `-User` to trustworthy origins (localhost).
//
// `Sec-Fetch-Mode` is NOT on the list: Node's own fetch sends it (measured:
// `sec-fetch-mode: cors`), and the healthcheck and the acceptance suite are
// Node clients.
//
// `POST /render` also demands `content-type: application/json`. A page that
// sets that type on a cross-origin request triggers a CORS preflight, which
// carries `Origin` and is refused here, so the POST is never sent. A page
// that avoids the preflight with `text/plain` gets a 415. Either barrier
// alone would hold; both cost nothing.

const BROWSER_HEADERS = ['origin', 'sec-fetch-site', 'sec-fetch-dest', 'sec-fetch-user'];

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
