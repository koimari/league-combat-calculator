/**
 * Run `static/js/app.js`'s control-family gating headlessly.
 *
 * Usage: node capability_gates_harness.mjs <app.js> <fixture.json>
 * The fixture supplies `capabilities` (what `/api/config` publishes, with any
 * control family the test wants refused). stdout is JSON: `gates` (the
 * declared family -> selector table) and `refusals` (the families the
 * contract refuses, each with the reason the page will show).
 */
import { evaluate, harnessContext, runScript } from "./harness_context.mjs";

const [appPath, fixturePath] = process.argv.slice(2);
const context = harnessContext(fixturePath);
runScript(context, appPath, "app.js");

console.log(evaluate(context, `
  engine.capabilities = __fixture.capabilities;
  JSON.stringify({
    gates: CONTROL_FAMILY_GATES,
    refusals: refusedControlFamilies(),
  });
`));
