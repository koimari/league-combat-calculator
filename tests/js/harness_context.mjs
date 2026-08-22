/**
 * The VM context every `tests/js` harness runs a shipped script in.
 *
 * `static/js/*.js` expects a browser: enough globals to load without throwing,
 * and nothing that reaches the network or the clock.  Anything a script only
 * touches is a `stub()` — a proxy that answers every access with another
 * stub — so a harness declares only the globals whose behaviour it asserts.
 * `overrides` replaces any of them: a harness that drives DOM behaviour passes
 * its own `document`.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

export const noop = () => {};

export const stub = () => new Proxy(function () {}, {
  get: (target, key) => {
    if (key === Symbol.toPrimitive || key === "toString") return () => "";
    if (key === "then") return undefined;
    if (key === "length") return 0;
    return stub();
  },
  set: () => true,
  apply: () => stub(),
  has: () => false,
});

/** A VM context holding the fixture on `__fixture`, ready to run a script in. */
export function harnessContext(fixturePath, overrides = {}) {
  const context = {
    document: stub(),
    window: new Proxy({
      location: { search: "", href: "", hash: "", origin: "http://harness" },
      addEventListener: noop, removeEventListener: noop, dispatchEvent: noop,
      setTimeout, clearTimeout,
      matchMedia: () => ({ matches: false, addEventListener: noop }),
    }, { get: (t, k) => (k in t ? t[k] : stub()), set: (t, k, v) => ((t[k] = v), true) }),
    navigator: { userAgent: "node" },
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    fetch: () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
    console,
    setTimeout, clearTimeout, setInterval, clearInterval, requestAnimationFrame: noop,
    CustomEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init); } },
    Event: class { constructor(type) { this.type = type; } },
    URL, URLSearchParams, TextEncoder, TextDecoder, structuredClone,
    __fixture: JSON.parse(readFileSync(fixturePath, "utf8")),
    ...overrides,
  };
  context.globalThis = context;
  context.self = context;
  return vm.createContext(context);
}

/** Run one shipped script in the context, under its own filename. */
export function runScript(context, path, filename) {
  vm.runInContext(readFileSync(path, "utf8"), context, { filename });
}

/**
 * Evaluate a snippet in the same context.  A script's `const` bindings live in
 * the context's global lexical scope, which only another script in that same
 * context can reach — which is why a harness reports through this.
 */
export function evaluate(context, source) {
  return vm.runInContext(source, context);
}
