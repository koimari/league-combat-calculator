/**
 * Run `static/js/app.js`'s real rune-page code headlessly.
 *
 * Usage: node rune_page_harness.mjs <app.js> <fixture.json>
 * The fixture supplies `runes`, `shards` and `capabilities` (what
 * `/api/config` publishes) and `page` (what the user picked). stdout is JSON: `payload` (the rune
 * half of the build the UI would POST), `statCard` (what the stat card asks
 * `/api/loadout-stats` for), `rows` (the rendered slot markup),
 * `shardChoices` (what each shard row offers), `picks` (the page after each
 * replayed minor-rune pick) and `copied` (the page after Copy A -> B).
 */
import { evaluate, harnessContext, runScript } from "./harness_context.mjs";

const [appPath, fixturePath] = process.argv.slice(2);
const context = harnessContext(fixturePath);
runScript(context, appPath, "app.js");

console.log(evaluate(context, `
  engine.capabilities = __fixture.capabilities;
  engine.runes = __fixture.runes;
  engine.keystones = __fixture.runes.filter((rune) => rune.row === 0);
  engine.runeShards = __fixture.shards;
  state.attacker.keystoneA = __fixture.page.keystone;
  state.attacker.minorRunesA = __fixture.page.minorRunes;
  state.attacker.statShardsA = __fixture.page.statShards;
  state.attacker.runeOptionsA = __fixture.page.runeOptions;
  // A synthetic counted option proves the picker renders from the declared
  // kind rather than assuming every option is a switch. No rune declares a
  // COUNT option yet; units B and C will (Legend stacks, the game minute).
  engine.runes = engine.runes.map((rune) => (
    rune.name === __fixture.page.minorRunes[2]
      ? { ...rune, options: [...(rune.options || []), __fixture.countedOption] }
      : rune
  ));
  const build = engineBuild("A");
  const rows = runePageRows("A");
  const statCard = loadoutStatsPayload();
  copyRunePage("A", "B");
  // Every pick in \`picks\`, replayed through the production handler, with the
  // five minor-rune slots as they stand after each one.  Last, because it
  // moves the page every other reading above is taken from.
  const picks = (__fixture.picks || []).map((name) => {
    pickMinorRune("A", name);
    return [name, [...state.attacker.minorRunesA]];
  });
  JSON.stringify({
    payload: {
      keystone: build.keystone,
      minor_runes: build.minor_runes,
      stat_shards: build.stat_shards,
      rune_options: build.rune_options,
    },
    statCard,
    rows,
    shardChoices: [0, 1, 2].map((index) => statShardChoices(index).map((option) => option.name)),
    picks,
    sides: ["attacker.keystoneA", "attacker.minorRunesB.3", "attacker.statShardsB.0", "attacker.buildA.2"].map(pickerSide),
    copied: {
      keystone: state.attacker.keystoneB,
      minorRunes: state.attacker.minorRunesB,
      statShards: state.attacker.statShardsB,
      runeOptions: state.attacker.runeOptionsB,
    },
  });
`));
