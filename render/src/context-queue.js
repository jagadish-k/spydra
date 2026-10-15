// Context-slot queue (spec 012 §2): at most `max` contexts exist at once;
// the next request waits up to `waitMs` for a slot, then 503s. Factored out
// of the server so the cap logic is testable without a browser.

/**
 * Thrown/rejected when no context became available within the queue window.
 * The HTTP layer maps this to 503 — backpressure, not failure.
 */
export class QueueFullError extends Error {
  constructor(waitMs) {
    super(`no context available within ${waitMs}ms`);
    this.name = 'QueueFullError';
  }
}

export class ContextQueue {
  /**
   * @param {number} max concurrent contexts (RENDER_CONTEXTS, default 3)
   * @param {number} waitMs how long an overflowing request queues before 503
   * @param {{ setTimeout: typeof setTimeout, clearTimeout: typeof clearTimeout }} [timers]
   *        injectable so tests can fake the clock
   */
  constructor(max, waitMs = 5000, timers) {
    this.max = max;
    this.waitMs = waitMs;
    this._timers = timers ?? {
      setTimeout: globalThis.setTimeout.bind(globalThis),
      clearTimeout: globalThis.clearTimeout.bind(globalThis),
    };
    this._active = 0;
    /** @type {{ resolve: () => void, reject: (e: unknown) => void, timer: unknown }}[] */
    this._waiters = [];
  }

  /** Contexts currently held. */
  get inUse() {
    return this._active;
  }

  /** Waiters currently queued (diagnostics/tests). */
  get queued() {
    return this._waiters.length;
  }

  /**
   * Take a context slot. Resolves when one is free; rejects with
   * QueueFullError after waitMs. On the fast path this never queues.
   *
   * @returns {Promise<void>}
   */
  acquire() {
    if (this._active < this.max && this._waiters.length === 0) {
      this._active++;
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const waiter = {
        resolve,
        reject,
        // no-floating-promise style deliberate: rejection is the signal
        timer: this._timers.setTimeout(() => {
          const i = this._waiters.indexOf(waiter);
          if (i !== -1) this._waiters.splice(i, 1);
          reject(new QueueFullError(this.waitMs));
        }, this.waitMs),
      };
      this._waiters.push(waiter);
    });
  }

  /**
   * Give a slot back. If someone is queued, the slot transfers to them
   * (FIFO) and _active does not dip — the cap is never exceeded, even for a
   * microsecond, which is the whole point.
   */
  release() {
    const next = this._waiters.shift();
    if (next) {
      this._timers.clearTimeout(next.timer);
      next.resolve();
    } else if (this._active > 0) {
      this._active--;
    }
  }
}
