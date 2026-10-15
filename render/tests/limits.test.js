// Truncation + limits (spec 012 §3): a >10 MB HTML body is truncated and
// flagged, never passed through whole.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { truncateHtml, MAX_HTML_BYTES, MAX_BODY_BYTES } from '../src/limits.js';

test('under the cap passes through unflagged', () => {
  const r = truncateHtml('<!doctype html><p>hello</p>');
  assert.equal(r.truncated, false);
  assert.equal(r.html, '<!doctype html><p>hello</p>');
});

test('exactly at the cap is not truncated', () => {
  // 1-char ASCII string of exactly MAX_HTML_BYTES bytes
  const exact = 'a'.repeat(MAX_HTML_BYTES);
  const r = truncateHtml(exact);
  assert.equal(r.truncated, false);
  assert.equal(r.html, exact);
});

test('one byte over the cap truncates and flags', () => {
  const over = 'a'.repeat(MAX_HTML_BYTES + 1);
  const r = truncateHtml(over);
  assert.equal(r.truncated, true);
  assert.equal(r.html, 'a'.repeat(MAX_HTML_BYTES)); // clean cut, nothing split
});

test('multibyte content cut mid-sequence flags and stays within the byte cap', () => {
  // 3 bytes/char against an even cap: the cut MUST land mid-sequence, so a
  // regression that lets the decoded U+FFFD push past the cap fails here
  // (the reviewer's finding — é never split, € always does).
  const over = '€'.repeat(Math.floor(MAX_HTML_BYTES / 3) + 10);
  const r = truncateHtml(over);
  assert.equal(r.truncated, true);
  assert.ok(Buffer.byteLength(r.html, 'utf8') <= MAX_HTML_BYTES);
});

test('the two caps are what spec 012 §3 says', () => {
  assert.equal(MAX_BODY_BYTES, 64 * 1024);
  assert.equal(MAX_HTML_BYTES, 10 * 1024 * 1024);
});
