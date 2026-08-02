# Architecture

The calculator separates sourced data, combat rules, scenario composition, optimization, and presentation. A value or rule should have one owner.

## Request path

```text
League Wiki cache
  -> data_fetcher.py
  -> scenario.py / stats.py
  -> champions/* + item_effects.py + rune_effects.py
  -> pipeline.py
  -> damage.py
  -> app.py
  -> app.js
```

`src/calculator/data_updater.py` is the only network-writing path. Runtime calculations read the tracked cache through `data_fetcher.py`.

## Rules and ownership

- `stats.py` applies level growth, item stats, role-quest modifiers, and external ally stat effects.
- `resistance.py` owns armor, magic resistance, and penetration order.
- `item_effects.py` owns item values and effect formulas. Item-specific numbers do not belong in routes or the interface.
- `rune_effects.py` owns keystone rune values and effect formulas the same way, reading `data/runes.json` (parsed from the wiki's rune data templates by `rune_parser.py`). Only compiled keystones are selectable; the rest are served greyed out and fail closed if requested.
- `item_coverage.py` classifies each optimizer candidate as modelled, reviewed stats-only, blocked, or pending review. New passive or active text fails closed until it is explicitly classified.
- `champions/<name>.py` owns reviewed champion formulas, options, and assumptions. The generic parser is useful for development coverage but is not a public exactness claim.
- `loadout_rules.py` validates inventory capacity, boot tiers, duplicate items, and mutually exclusive item groups for both manual builds and optimization.
- `defensive_effects.py` resolves defenses that are ready when combat begins. Starting shields, basic-damage modifiers, capped post-mitigation reductions, critical-strike reductions, and one-rotation threshold shields come from revision-backed Wiki mechanics. Timed threshold shields remain fail-closed until every auto and item-effect event has a certified timestamp; unregistered defenses remain explicitly outside the model.
- `ally_effects.py` compiles opt-in outgoing ally effects only when a sourced, tested rule exists.

## Combat model

`pipeline.py` validates ranks and request bounds, calculates stats, parses the selected champion, and calls the fight engine.

`damage.py` owns the fight state. It schedules casts, applies resource costs and regeneration, prices typed damage parts, updates mitigation, simulates auto attacks, and applies item effects. A shared ordered-damage ledger reconstructs accepted casts and exact typed row composition for threshold and shield consumers. Auto attacks carry their simulated per-swing times and damage; item effects without authored events remain explicitly coarse. Results include the accepted cast timeline, resource spent and remaining, per-source damage, TDD, health damage, shield absorption, and effective resistances.

The cast schedule is chronological. Some legacy damage layers still aggregate repeated casts by source after scheduling; those outputs must not be described as event-perfect until their mechanic has a dedicated timeline rule.

## Scenarios

`scenario.py` resolves up to five enemies and four allies. Each roster card owns its champion, level, boots, items, item state, role, and quest state. Base health and bonus health remain separate.

The same selected damage package is evaluated against every selected enemy. Target-limited item procs are allocated once across the roster. Aggregate TDD is the sum of the resulting per-target damage, not a synthetic average target.

## Optimization

`optimizer.py` scores legal builds through the same `run_fight` pipeline used by manual calculations. The objective is modeled TDD unless the user explicitly selects physical or magic damage.

A one-item opening is searched exhaustively across modelled candidates. It is certified as best in slot only when candidate coverage is complete. If any available candidate is withheld, the result is labelled `Best modelled` and includes the excluded items and reasons. Complete builds use multi-start greedy search and hill climbing and are never labelled certified best in slot. The response includes the search guarantee, candidate-coverage receipt, build count, gold cost, and a distinct runner-up. Build A and Build B may never be identical.

## Public boundary

`app.py` parses bounded requests and exposes stable JSON. `static/js/app.js` renders the scenario and results; it contains no champion or item formulas.

Reviewed champion modules are enabled as attackers. Every cached champion can be used as an ally or target for independently derived base and item stats. Missing attacker mechanics fail closed. Missing ally or defensive mechanics are disclosed as unmodeled context.

## Verification

- `pytest` covers calculations and API contracts.
- `pylint` enforces source quality.
- `scripts/golden_snapshot.py` detects numerical drift across full-pipeline scenarios.
- browser verification covers empty start, selection, level changes, roster builds, A/B comparison, optimization, sharing, themes, and responsive layout.

Expected numerical changes require a sourced explanation and a reviewed golden-baseline update.
