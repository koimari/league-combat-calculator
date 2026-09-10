/**
 * Drive static/js/scoreboard.js's real paste handler with files that never decode.
 *
 *   node scoreboard_paste_harness.mjs <scoreboard.js> <cases.json>
 *
 * Each case names a clipboard file by `type` and `size`; `createImageBitmap`
 * rejects every one, so what the status line says is the reader's own
 * refusal. Prints `{ name: statusText }`.
 */
import { readFileSync } from "node:fs";
import { harnessContext, noop, runScript } from "./harness_context.mjs";

const [scriptPath, casesPath] = process.argv.slice(2);
const cases = JSON.parse(readFileSync(casesPath, "utf8"));

const element = () => ({
  textContent: "", innerHTML: "", disabled: false, open: false, value: "", files: [],
  showModal() { this.open = true; }, close: noop, addEventListener: noop, querySelector: () => null,
});
const elements = {};
const listeners = {};
const document = {
  getElementById: (id) => (elements[id] ??= element()),
  addEventListener: (type, handler) => { listeners[type] = handler; },
};
const context = harnessContext(casesPath, {
  document,
  loadSharedBuildIntoAnalyst: noop,
  createImageBitmap: () => Promise.reject(new Error("no decoder")),
  fetch: () => new Promise(noop),
  performance,
});
runScript(context, scriptPath, "scoreboard.js");

const settled = () => new Promise((resolve) => setTimeout(resolve, 0));
const out = {};
for (const { name, type, size } of cases) {
  listeners.paste({ clipboardData: { files: [{ type, size }] }, target: null, preventDefault: noop });
  await settled();
  out[name] = elements.scoreboardStatus.textContent;
}
process.stdout.write(JSON.stringify(out));
