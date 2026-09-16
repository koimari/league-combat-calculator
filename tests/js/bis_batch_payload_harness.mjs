/**
 * Run `static/js/app.js`'s two BIS payload builders headlessly.
 *
 * Usage: node bis_batch_payload_harness.mjs <app.js> <fixture.json>
 * The fixture supplies `champion` (the main attacker), `enemy` (the one roster
 * card) and `paths` (the paths to build a payload for). stdout is JSON keyed
 * by path: `batch` is what `bisBatchSubjectPayload` answers and `slot` is what
 * `bisBackendPayload` answers, each `null` when that builder refuses the path.
 *
 * The split is the point. `/api/bis/batch` is addressed by CARD
 * (`targets.0`) and carries its slots in its own list; `/api/bis` is addressed
 * by SLOT (`targets.0.items.2`). Routing a card path through the slot builder
 * is what made the roster optimizer throw on its first call.
 */
import { evaluate, harnessContext, runScript } from "./harness_context.mjs";

const [appPath, fixturePath] = process.argv.slice(2);
const context = harnessContext(fixturePath);
runScript(context, appPath, "app.js");

console.log(evaluate(context, `
  state.attacker.champion = __fixture.champion;
  state.attacker.role = "bottom";
  state.targets = [newRosterLoadout("enemy")];
  state.targets[0].champion = __fixture.enemy;
  state.targets[0].role = "top";
  JSON.stringify(Object.fromEntries(__fixture.paths.map((path) => [path, {
    batch: bisBatchSubjectPayload(path),
    slot: bisBackendPayload(path),
  }])));
`));
