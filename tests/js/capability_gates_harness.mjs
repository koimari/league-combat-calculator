/**
 * Run `static/js/app.js`'s control-family gating headlessly.
 *
 * Usage: node capability_gates_harness.mjs <app.js> <fixture.json>
 * The fixture supplies `capabilities` (what `/api/config` publishes, with any
 * control family the test wants refused). stdout is JSON: `gates` (the
 * declared family -> selector table) and `refusals` (the families the
 * contract refuses, each with the reason the page will show).
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [appPath, fixturePath] = process.argv.slice(2);

const noop = () => {};
const stub = () => new Proxy(function () {}, {
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
};
context.globalThis = context;
context.self = context;
vm.createContext(context);
vm.runInContext(readFileSync(appPath, "utf8"), context, { filename: "app.js" });

console.log(vm.runInContext(`
  engine.capabilities = __fixture.capabilities;
  JSON.stringify({
    gates: CONTROL_FAMILY_GATES,
    refusals: refusedControlFamilies(),
  });
`, context));
