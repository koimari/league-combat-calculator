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
import { evaluate, harnessContext, runScript } from "./harness_context.mjs";

const [appPath, fixturePath] = process.argv.slice(2);
const context = harnessContext(fixturePath);
runScript(context, appPath, "app.js");

console.log(evaluate(context, `
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
`));
