/**
 * Run `static/js/eventorder.js` headlessly against the result signal app.js
 * publishes.
 *
 * Usage: node event_order_harness.mjs <eventorder.js> <fixture.json>
 * The fixture supplies `results` — each one dispatched as one
 * `scryglass:result` detail, in order. stdout is JSON: one `{ hidden, html }`
 * per dispatch, read off the #eventOrderPanel mount.
 */
import { harnessContext, runScript } from "./harness_context.mjs";

const [scriptPath, fixturePath] = process.argv.slice(2);

// eventorder.js is DOM behaviour, so this harness supplies a real document
// rather than the shared stub: a mount to render into and an event bus.
const mount = { innerHTML: "", hidden: true, contains: () => false };
const listeners = {};
const document = {
  readyState: "complete",
  body: {},
  getElementById: (id) => (id === "eventOrderPanel" ? mount : null),
  querySelector: () => null,
  addEventListener: (type, handler) => {
    (listeners[type] = listeners[type] || []).push(handler);
  },
  dispatchEvent: (event) => {
    (listeners[event.type] || []).forEach((handler) => handler(event));
    return true;
  },
};

// The panel re-renders its last payload when the result area changes.
class MutationObserver {
  constructor(callback) { this.callback = callback; }
  observe() {}
  disconnect() {}
}

const context = harnessContext(fixturePath, { document, MutationObserver });
runScript(context, scriptPath, "eventorder.js");

const seen = context.__fixture.results.map((result) => {
  document.dispatchEvent({ type: "scryglass:result", detail: result });
  return { hidden: mount.hidden, html: mount.innerHTML };
});
console.log(JSON.stringify({ seen, listened: (listeners["scryglass:result"] || []).length }));
