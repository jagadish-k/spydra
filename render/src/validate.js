// Request validation for POST /render (spec 012 §1). Pure: no browser, no
// I/O — everything here is unit-tested without Playwright.

import { MAX_TIMEOUT_MS } from './limits.js';

export const DEFAULT_TIMEOUT_MS = 20_000;
export const DEFAULT_WAIT_UNTIL = 'networkidle';
export const DEFAULT_BLOCK_RESOURCES = ['image', 'font', 'media'];

const WAIT_UNTIL = new Set(['load', 'domcontentloaded', 'networkidle']);

// Playwright's request.resourceType() vocabulary. Anything else in
// block_resources can never match a route, so it is a caller bug: 422.
const RESOURCE_TYPES = new Set([
  'document',
  'stylesheet',
  'image',
  'media',
  'font',
  'script',
  'texttrack',
  'xhr',
  'fetch',
  'eventsource',
  'websocket',
  'manifest',
  'other',
]);

/**
 * @typedef {Object} RenderRequest
 * @property {string} url
 * @property {'load'|'domcontentloaded'|'networkidle'} wait_until
 * @property {string} [wait_for_selector]
 * @property {number} timeout_ms
 * @property {string[]} block_resources
 * @property {string} [user_agent]
 * @property {Record<string, string>} [extra_headers]
 */

/**
 * Validate a parsed /render body.
 *
 * @param {unknown} body
 * @returns {{ ok: true, value: RenderRequest } | { ok: false, error: string }}
 *          ok:false is always a 422 per the spec's status table.
 */
export function validateRequest(body) {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return bad('body must be a JSON object');
  }

  const { url, wait_until, wait_for_selector, timeout_ms, block_resources, user_agent, extra_headers } =
    body;

  if (typeof url !== 'string' || url === '') return bad('url is required');
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return bad('url is malformed');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return bad('url must be http or https');
  }
  if (parsed.hostname === '') return bad('url has no host');

  let wait = DEFAULT_WAIT_UNTIL;
  if (wait_until !== undefined) {
    if (typeof wait_until !== 'string' || !WAIT_UNTIL.has(wait_until)) {
      return bad('wait_until must be one of load, domcontentloaded, networkidle');
    }
    wait = wait_until;
  }

  if (wait_for_selector !== undefined && (typeof wait_for_selector !== 'string' || wait_for_selector === '')) {
    return bad('wait_for_selector must be a non-empty string');
  }

  let timeout = DEFAULT_TIMEOUT_MS;
  if (timeout_ms !== undefined) {
    if (typeof timeout_ms !== 'number' || !Number.isInteger(timeout_ms) || timeout_ms <= 0) {
      return bad('timeout_ms must be a positive integer');
    }
    timeout = clampTimeout(timeout_ms);
  }

  let block = DEFAULT_BLOCK_RESOURCES;
  if (block_resources !== undefined) {
    if (!Array.isArray(block_resources)) return bad('block_resources must be an array');
    if (block_resources.some((r) => typeof r !== 'string' || !RESOURCE_TYPES.has(r))) {
      return bad('block_resources contains an unknown resource type');
    }
    block = block_resources;
  }

  if (user_agent !== undefined && (typeof user_agent !== 'string' || user_agent === '')) {
    return bad('user_agent must be a non-empty string');
  }

  if (extra_headers !== undefined) {
    if (typeof extra_headers !== 'object' || extra_headers === null || Array.isArray(extra_headers)) {
      return bad('extra_headers must be an object');
    }
    for (const [k, v] of Object.entries(extra_headers)) {
      if (typeof v !== 'string') return bad(`extra_headers.${k} must be a string`);
    }
  }

  const value = { url, wait_until: wait, timeout_ms: timeout, block_resources: block };
  if (wait_for_selector !== undefined) value.wait_for_selector = wait_for_selector;
  if (user_agent !== undefined) value.user_agent = user_agent;
  if (extra_headers !== undefined) value.extra_headers = extra_headers;
  return { ok: true, value };
}

/**
 * Clamp a requested timeout to the 30 s hard ceiling (spec 012 §3).
 * @param {number} ms
 * @returns {number}
 */
export function clampTimeout(ms) {
  return Math.min(ms, MAX_TIMEOUT_MS);
}

/** @returns {{ ok: false, error: string }} */
function bad(error) {
  return { ok: false, error };
}
