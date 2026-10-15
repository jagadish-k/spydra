// URL / request validation matrix (spec 012 §1). No browser, no network.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateRequest, clampTimeout, DEFAULT_TIMEOUT_MS, DEFAULT_WAIT_UNTIL, DEFAULT_BLOCK_RESOURCES } from '../src/validate.js';
import { MAX_TIMEOUT_MS } from '../src/limits.js';

test('missing or non-string url → 422', () => {
  for (const body of [undefined, {}, { url: 42 }, { url: '' }, { url: null }]) {
    const r = validateRequest({ wait_until: 'load', ...body });
    assert.equal(r.ok, false, JSON.stringify(body));
    assert.equal(r.ok, false);
  }
});

test('malformed url → 422', () => {
  for (const url of ['not a url', 'http://', 'https://', '//example.com', 'example.com/x']) {
    const r = validateRequest({ url });
    assert.equal(r.ok, false, url);
  }
});

test('non-http(s) protocol → 422', () => {
  for (const url of ['ftp://example.com', 'file:///etc/passwd', 'about:blank', 'chrome://version']) {
    const r = validateRequest({ url });
    assert.equal(r.ok, false, url);
  }
});

test('unknown wait_until → 422', () => {
  for (const wait_until of ['idle', 'NETWORKIDLE', '', 3, null, 'load ']) {
    const r = validateRequest({ url: 'https://example.com', wait_until });
    assert.equal(r.ok, false, JSON.stringify(wait_until));
  }
});

test('bad timeout_ms / block_resources / extra_headers shapes → 422', () => {
  const ok = { url: 'https://example.com' };
  for (const body of [
    { ...ok, timeout_ms: -1 },
    { ...ok, timeout_ms: 0 },
    { ...ok, timeout_ms: 1.5 },
    { ...ok, timeout_ms: '20000' },
    { ...ok, block_resources: 'image' },
    { ...ok, block_resources: ['image', 'css'] },
    { ...ok, block_resources: [42] },
    { ...ok, extra_headers: 'x-a: 1' },
    { ...ok, extra_headers: { 'x-a': 1 } },
    { ...ok, user_agent: '' },
  ]) {
    const r = validateRequest(body);
    assert.equal(r.ok, false, JSON.stringify(body));
  }
});

test('minimal valid request gets every default', () => {
  const r = validateRequest({ url: 'https://example.com/products/x' });
  assert.equal(r.ok, true);
  assert.deepEqual(r.value, {
    url: 'https://example.com/products/x',
    wait_until: DEFAULT_WAIT_UNTIL, // networkidle
    timeout_ms: DEFAULT_TIMEOUT_MS, // 20000
    block_resources: DEFAULT_BLOCK_RESOURCES, // image, font, media
  });
  assert.equal(DEFAULT_WAIT_UNTIL, 'networkidle');
  assert.equal(DEFAULT_TIMEOUT_MS, 20000);
  assert.deepEqual(DEFAULT_BLOCK_RESOURCES, ['image', 'font', 'media']);
});

test('valid optional fields pass through untouched', () => {
  const r = validateRequest({
    url: 'http://example.com',
    wait_until: 'load',
    wait_for_selector: '.price',
    timeout_ms: 5000,
    block_resources: [],
    user_agent: 'Spydra/1.0',
    extra_headers: { 'x-api': 'no' },
  });
  assert.equal(r.ok, true);
  assert.deepEqual(r.value, {
    url: 'http://example.com',
    wait_until: 'load',
    wait_for_selector: '.price',
    timeout_ms: 5000,
    block_resources: [],
    user_agent: 'Spydra/1.0',
    extra_headers: { 'x-api': 'no' },
  });
});

test('timeout is clamped to the 30s hard ceiling, never raised', () => {
  assert.equal(clampTimeout(2000), 2000);
  assert.equal(clampTimeout(MAX_TIMEOUT_MS), MAX_TIMEOUT_MS);
  assert.equal(clampTimeout(MAX_TIMEOUT_MS + 1), MAX_TIMEOUT_MS);
  assert.equal(clampTimeout(999_999_999), MAX_TIMEOUT_MS);
  const r = validateRequest({ url: 'https://example.com', timeout_ms: 120000 });
  assert.equal(r.ok, true);
  assert.equal(r.value.timeout_ms, MAX_TIMEOUT_MS);
});
