// Hard limits from spec 012 §3. This service fetches arbitrary URLs with a
// real browser; the limits are the cheap half of the safety story (the
// network isolation in compose is the other half, ADR-0023).

/** Request body cap. Larger bodies are refused before they are buffered. */
export const MAX_BODY_BYTES = 64 * 1024;

/** Response HTML cap. Beyond it we truncate and flag, never stream whole. */
export const MAX_HTML_BYTES = 10 * 1024 * 1024;

/** No request can ask for more render time than this, whatever it sends. */
export const MAX_TIMEOUT_MS = 30_000;

/**
 * Truncate `html` to MAX_HTML_BYTES, flagging when it happened.
 *
 * @param {string} html
 * @returns {{ html: string, truncated: boolean }}
 */
export function truncateHtml(html) {
  const buf = Buffer.from(html, 'utf8');
  if (buf.length <= MAX_HTML_BYTES) return { html, truncated: false };
  // toString() turns a UTF-8 sequence split at the cut into U+FFFD — an
  // honest marker at the truncation point, cheaper than seeking a boundary.
  return { html: buf.subarray(0, MAX_HTML_BYTES).toString('utf8'), truncated: true };
}
