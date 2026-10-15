// Context-queue cap logic (spec 012 §2): the 4th concurrent request waits,
// then 503s — proved here with a fake clock so no browser is involved.

import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { ContextQueue, QueueFullError } from '../src/context-queue.js';

test('hands out exactly max slots without queueing', async () => {
  const q = new ContextQueue(3, 5000);
  await q.acquire();
  await q.acquire();
  await q.acquire();
  assert.equal(q.inUse, 3);
  assert.equal(q.queued, 0);
  q.release();
  q.release();
  q.release();
  assert.equal(q.inUse, 0);
});

test('4th acquire waits, then takes a released slot (FIFO)', async () => {
  const q = new ContextQueue(3, 5000);
  for (let i = 0; i < 3; i++) await q.acquire();
  let fourthResolved = false;
  const fourth = q.acquire().then(() => {
    fourthResolved = true;
  });
  await Promise.resolve(); // let microtasks settle — the 4th must NOT resolve
  assert.equal(fourthResolved, false);
  assert.equal(q.queued, 1);

  q.release(); // slot transfers to the waiter; in-use must not dip below cap
  await fourth;
  assert.equal(q.inUse, 3);
  assert.equal(q.queued, 0);
});

test('4th acquire rejects with QueueFullError after the 5s window', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const q = new ContextQueue(3, 5000); // constructed after enable → mocked clock
    for (let i = 0; i < 3; i++) await q.acquire();

    const fourth = q.acquire();
    mock.timers.tick(4999);
    let settled = false;
    fourth.catch(() => {
      settled = true;
    });
    await Promise.resolve();
    assert.equal(settled, false, 'must still be queued at 4999ms');

    mock.timers.tick(1);
    await assert.rejects(fourth, (e) => e instanceof QueueFullError);
    assert.equal(q.queued, 0, 'timed-out waiter must leave the queue');
    assert.equal(q.inUse, 3, 'the cap holders are untouched');
  } finally {
    mock.timers.reset();
  }
});

test('a timed-out waiter does not steal a later-released slot', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const q = new ContextQueue(1, 1000);
    await q.acquire();
    const loser = q.acquire();
    mock.timers.tick(1000);
    await assert.rejects(loser, QueueFullError);

    q.release(); // slot free, queue empty
    assert.equal(q.inUse, 0);
    await q.acquire(); // fast path again
    assert.equal(q.inUse, 1);
  } finally {
    mock.timers.reset();
  }
});
