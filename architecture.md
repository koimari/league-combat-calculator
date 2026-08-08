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

`src/calculator/data_updater.py` is the only writer of the tracked runtime caches (champions/items/runes.json) and only through the atomic `data_registry.write_runtime_cache` API; `data_fetcher.py` is read-only. Evidence/derived writers are declared in `data_registry.WRITERS` (decompose_wiki -> data/wiki*, decompose_binaries -> data/bin, patch_regression -> data/gamefiles+staleness.json, refresh_economics_data -> economics-sourced.json); every data/ subtree has an explicit, repo-anchored owner enforced by tests/test_data_writer_inventory.py. `item_source.py` owns what the cache records about an item's sources — see below.

## Rules and ownership

- `stats.py` applies level growth, item stats, role-quest modifiers, and external ally stat effects.
- `resistance.py` owns armor, magic resistance, and penetration order.
- `item_effects.py` owns item values and effect formulas. Item-specific numbers do not belong in routes or the interface.
- `rune_effects.py` owns keystone rune values and effect formulas the same way, reading `data/runes.json` (parsed from the wiki's rune data templates by `rune_parser.py`). Only compiled keystones are selectable; the rest are served greyed out and fail closed if requested.
- `item_source.py` owns the ingested-source view of an item: the complete branch list of every passive and active, map/mode availability, champion-granted and acquisition state, and the audit that reconciles the Wiki item table against Riot's description. Selection pools ask it whether an item is an ordinary Summoner's Rift purchase; nothing decides that from a name list. A source divergence is either a reviewed entry in `ACKNOWLEDGED_SOURCE_CONFLICTS` or it stops patch day — neither source is silently preferred.
- `item_coverage.py` classifies each optimizer candidate as modelled, reviewed stats-only, blocked, or pending review. New passive or active text fails closed until it is explicitly classified. It answers whether a mechanic is *modelled*; `item_source.py` answers whether it was *ingested*.
- Full-entry source review is mandatory: every in-scope item and champion is checked against its complete League Wiki parent page before promotion. The exact receipt, effect inventory, module-slot coverage, hashes, and runtime reason are produced by `scripts/full_entry_audit.py`; see `docs/full-wiki-entry-review-requirement.md`.
- The item umbrella gate is separate from page review: `scripts/item_umbrella_audit.py` checks every classic-SR source record for explicit attacker and target coverage, compares manual/roster/optimizer pools, and fails on review-pending, unexplained, or unresolved source conflicts. Its receipt is `docs/item-umbrella-audit.json`.
- `champions/<name>.py` owns reviewed champion formulas, options, and assumptions. The generic parser is useful for development coverage but is not a public exactness claim.
- `loadout_rules.py` validates inventory capacity, boot tiers, duplicate items, and mutually exclusive item groups for both manual builds and optimization.
- `shield_ledger.py` owns what a damage instance does to a defender: timed-grant expiry, typed-pool consumption, Lifeline arming, general-pool consumption, health damage, overkill, and every absorbed total. All five absorption paths — both ordered walks in `damage.py`, the authoritative receipt walk, and both damage branches of the compiled score walk — call `absorb()` over a `ShieldPools`; they differ only in where that object is stored. Shields enter through `grant()` so a pool total and its expiry sub-ledger can never disagree, and defenses become pools through the one `build_pools()`, so the one-pair engine and the coupled ledger cannot stage the same item differently. Adding a shield mechanic or changing absorption order is one edit (issue #159).
- `defensive_effects.py` resolves defenses that are ready when combat begins. Starting shields, basic-damage modifiers, capped post-mitigation reductions, critical-strike reductions, and one-rotation threshold shields come from revision-backed Wiki mechanics. Timed threshold shields are priced from the certified event ledger; a timed fight with any uncertified damage source is withheld after computation, naming the coarse sources. Unregistered defenses remain explicitly outside the model.
- `ally_effects.py` compiles opt-in outgoing ally effects only when a sourced, tested rule exists.

## Combat model

`pipeline.py` validates ranks and request bounds, calculates stats, parses the selected champion, and calls the fight engine.

`damage.py` owns the fight state. It schedules casts, applies resource costs and regeneration, prices typed damage parts, updates mitigation, simulates auto attacks, and applies item effects. A shared ordered-damage ledger reconstructs accepted casts and exact typed row composition for threshold and shield consumers. Auto attacks carry their simulated per-swing times and damage; item effects without authored events remain explicitly coarse. Results include the accepted cast timeline, resource spent and remaining, per-source damage, TDD, health damage, shield absorption, and effective resistances.

The cast schedule is chronological. Some legacy damage layers still aggregate repeated casts by source after scheduling; those outputs must not be described as event-perfect until their mechanic has a dedicated timeline rule.

## Scenarios

`scenario.py` resolves up to five enemies and four allies. Each roster card owns its champion, level, boots, items, item state, role, and quest state. Base health and bonus health remain separate.

The same selected damage package is evaluated against every selected enemy. Target-limited item procs are allocated once across the roster. Aggregate TDD is the sum of the resulting per-target damage, not a synthetic average target.

`participant_timeline.py` composes the per-pair event ledgers into one coupled survival walk. Reactive strike-back items (`item_effects.thorns_effects`) live here rather than in the one-attacker engine: each modeled basic attack that strikes a wearer schedules mitigated return damage and a Grievous Wounds window onto the striker, linked to the triggering event so retaliation dies with a skipped strike. In a fight with no incoming attacks, a thorns item correctly contributes nothing.

## Optimization

`optimizer.py` scores legal builds through the same `run_fight` pipeline used by manual calculations. The objective is modeled TDD unless the user explicitly selects physical or magic damage.

A one-item opening is searched exhaustively across modelled candidates. It is certified as best in slot only when candidate coverage is complete. If any available candidate is withheld, the result is labelled `Best modelled` and includes the excluded items and reasons. Complete builds use multi-start greedy search and hill climbing and are never labelled certified best in slot. The response includes the search guarantee, candidate-coverage receipt, build count, gold cost, and a distinct runner-up. Build A and Build B may never be identical.

Coupled searches score thousands of candidates against one fixed roster, so per-search caches reuse everything a candidate swap cannot change: roster-to-roster pair fights always, fights into the candidate whenever its defensive signature repeats (`participant_timeline._target_overrides` is both the engine contract and the cache key), pre-enriched pair event packets carrying precomputed survival-walk sort keys and once-compiled typed actions the receipt composition reuses across evaluations (issue #169), and a score memo for exactly repeated ordered builds that replays the recorded ordering-audit contribution. Candidate evaluation asks `build_participant_timeline` for the score-only receipt (`include_receipt=False`) — identical numbers, no public serialization.

Scoring additionally runs through a per-search `CoupledSearchContext`: every event compiles once into a flat walk action (sort key, participant indices, trigger slot, pre-resolved Grievous pack, heal category), the signature-independent roster fights — including a roster holder's active Warmog's Heart ticks — compile once per search, the fights into each distinct candidate defensive signature compile once per signature, and an evaluation then compiles only the main champion's fresh outgoing fights before running a no-copy survival walk with the same arithmetic, operation order, and rounding as the receipt walk — per-attacker sums replay the legacy list order so float addition cannot drift, and every pair fight carries the same roster-target allocation the receipt composition sets. A transition the compiler cannot stage fails closed onto the receipt walk with a named receipt; nothing is silently dropped. The engine supports this with caller-owned claims on `run_fight` (`validated`, `precomputed_stats`, `score_only`): score mode skips only provably-unread outputs (the one-pair shield outcome unless Protoplasm or a takedown-scanning support item needs it, display splits, per-cast resource receipt rows), and a champion with no self-heal rules (`healing.HEALING_RULE_CHAMPIONS`) and no heal-, execute-, or event-scan-relevant items returns its event ledger as light tuples instead of dict rows — the tuple predicate owns that item knowledge, so score-only rows always carry every field that prices a heal, a support packet, or an execute. Pure cached-JSON derivations (item stat blocks, ability leveling lookups, cast-time and resource-cost stamps) are memoized by object identity and re-verified on every hit so a data refresh can never serve stale values.

None of this changes which builds are evaluated or how they score: cache-vs-no-cache and fast-vs-legacy-walk equivalence are pinned by regression tests (`tests/test_participant_timeline.py`, `tests/test_optimizer.py`), and `scripts/bench_coupled_optimizer.py` reports the reference scenarios' builds, scores, and evaluation counts for manual comparison across changes.

## Public boundary

`app.py` parses bounded requests and exposes stable JSON. `static/js/app.js` renders the scenario and results from backend receipts only: it contains no champion or item formulas, no item-id literals, and no local damage/stat engine (issue #135 retired the duplicate in-browser engine and the 175% crit fallback). Stat cards are fed by `POST /api/loadout-stats`; scores, breakdowns, BIS, and both optimizers consume `/api/calculate`, `/api/bis`, and `/api/optimize`.

Reviewed champion modules are enabled as attackers. Every cached champion can be used as an ally or target for independently derived base and item stats. Missing attacker mechanics fail closed. Missing ally or defensive mechanics are disclosed as unmodeled context.

## Verification

- `pytest` covers calculations and API contracts.
- `pylint` enforces source quality.
- `scripts/golden_snapshot.py` detects numerical drift across full-pipeline scenarios.
- browser verification covers empty start, selection, level changes, roster builds, A/B comparison, optimization, sharing, themes, and responsive layout.

Expected numerical changes require a sourced explanation and a reviewed golden-baseline update.
