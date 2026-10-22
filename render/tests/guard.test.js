// ADR-0038's request-shape guard, as a pure function over request headers.
//
// The acceptance suite proves the guard on a running sidecar and a real
// browser. These cases pin the rule itself, one header at a time, because a
// header dropped from the list is exactly the mutation an end-to-end case
// can miss (a browser sends several of them at once, so removing one still
// leaves the request refused).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { refusal } from '../src/guard.js';

/** The shape `refusal` reads from `http.IncomingMessage`: node lowercases
 *  incoming header names, so these are lowercase too. */
function request(method, url, headers = {}) {
  return { method, url, headers };
}

const JSON_POST = { 'content-type': 'application/json' };

describe('ADR-0038 — headers only a browser sends are refused with 403', () => {
  for (const [name, value] of [
    ['origin', 'http://127.0.0.1:8099'],
    ['origin', 'null'], // a sandboxed iframe or a data: URL still sends one
    ['sec-fetch-site', 'same-site'],
    ['sec-fetch-dest', 'empty'],
    ['sec-fetch-user', '?1'],
  ]) {
    test(`${name}: ${value} on POST /render`, () => {
      const r = refusal(request('POST', '/render', { ...JSON_POST, [name]: value }));
      assert.equal(r?.status, 403);
    });

    test(`${name}: ${value} on GET /healthz`, () => {
      const r = refusal(request('GET', '/healthz', { [name]: value }));
      assert.equal(r?.status, 403, 'the guard runs before routing, on every path');
    });
  }

  test('a browser header outranks the content-type check', () => {
    // A page's CORS preflight never carries the JSON type, so a 415 here
    // would still refuse it. The order matters for what the refusal says:
    // the request is refused for what it IS, a browser, not for its body.
    const r = refusal(request('POST', '/render', { origin: 'http://127.0.0.1:8099' }));
    assert.equal(r?.status, 403);
  });
});

describe('ADR-0038 — the Node clients are still served', () => {
  test('sec-fetch-mode alone is not a browser (Node fetch sends it)', () => {
    assert.equal(refusal(request('GET', '/healthz', { 'sec-fetch-mode': 'cors' })), null);
    assert.equal(
      refusal(request('POST', '/render', { ...JSON_POST, 'sec-fetch-mode': 'cors' })),
      null,
    );
  });

  test("the worker's request shape: JSON, no browser headers", () => {
    const worker = { 'content-type': 'application/json', 'user-agent': 'python-httpx/1', accept: '*/*' };
    assert.equal(refusal(request('POST', '/render', worker)), null);
  });

  test('a JSON type with parameters, or in another case, is still JSON', () => {
    for (const type of ['application/json; charset=utf-8', 'Application/JSON']) {
      assert.equal(refusal(request('POST', '/render', { 'content-type': type })), null, type);
    }
  });
});

describe('ADR-0038 — POST /render demands application/json (415)', () => {
  for (const type of [undefined, 'text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data; boundary=x', 'application/jsonp']) {
    test(`content-type: ${type ?? '(none)'}`, () => {
      const headers = type === undefined ? {} : { 'content-type': type };
      assert.equal(refusal(request('POST', '/render', headers))?.status, 415);
    });
  }

  test('only POST /render: healthz needs no body type', () => {
    assert.equal(refusal(request('GET', '/healthz')), null);
  });
});
