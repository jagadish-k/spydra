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
  // A cut landing mid-UTF-8-sequence decodes to U+FFFD (3 bytes), which
  // would push the result past the cap — trim the replacement too, so the
  // returned string is never longer than MAX_HTML_BYTES.
  let cut = buf.subarray(0, MAX_HTML_BYTES).toString('utf8');
  if (Buffer.byteLength(cut, 'utf8') > MAX_HTML_BYTES) cut = cut.slice(0, -1);
  return { html: cut, truncated: true };
}
