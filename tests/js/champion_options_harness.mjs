/**
 * Run `static/js/app.js`'s real payload builder headlessly.
 *
 * Usage: node champion_options_harness.mjs <app.js> <fixture.json>
 * The fixture supplies `champion`, `options` (the backend's option contract),
 * `abilities` (the authored kit in static/data.json), `abilityForms` (the
 * champion's static/bis-profiles.json forms) and `variants` (slot -> the
 * Variant button clicked); app.js's own merge flattens those into the kit the
 * browser renders. stdout is JSON: `options` (the `champion_options` the UI
 * would POST), `bindings` (the module option each slot's Variant control
 * writes) and `kit` (each slot's variant names and their source form).
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

// app.js's `const` bindings live in the context's global lexical scope, which
// only another script in that same context can reach.
console.log(vm.runInContext(`
  // The kit the browser renders is app.js's own merge of the authored
  // abilities with the wiki forms — never a second flattening rule.
  DATA = { champions: [{ name: __fixture.champion, abilities: __fixture.abilities }] };
  mergeBisProfiles({ champions: { [__fixture.champion]: { abilities: __fixture.abilityForms } } });
  engine.championOptions = { [__fixture.champion]: { options: __fixture.options } };
  state.attacker.champion = __fixture.champion;
  state.attacker.championOptions = {};
  state.attacker.abilityInputs = Object.fromEntries(activeAbilityKit().map((ability) => [
    ability.slot,
    { rank: 1, casts: 1, hits: 1, variant: defaultFormVariantIndex(ability) },
  ]));
  // Replay the Variant click, mirror included, exactly as the handler does.
  Object.entries(__fixture.variants).forEach(([slot, index]) => {
    state.attacker.abilityInputs[slot].variant = index;
    syncGlobalFormVariants(slot, index);
  });
  JSON.stringify({
    options: engineChampionOptions(),
    bindings: Object.fromEntries(activeAbilityKit().map((ability) => [
      ability.slot,
      abilityOptionBinding(ability.slot, "ability_variants"),
    ])),
    kit: Object.fromEntries(activeAbilityKit().map((ability) => [
      ability.slot,
      (ability.variants || []).map((variant, index) => ({
        name: variant.name,
        form: variantForm(ability, index),
      })),
    ])),
    selected: Object.fromEntries(activeAbilityKit().map((ability) => [
      ability.slot,
      abilityInput(ability.slot).variant,
    ])),
  });
`, context));
