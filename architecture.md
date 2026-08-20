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
- The item umbrella gate is separate from page review: `scripts/item_umbrella_audit.py` checks every classic-SR source record for explicit attacker and target coverage, compares manual/roster/optimizer pools, and fails on review-pending, unexplained, or unresolved source conflicts. Its receipt is `docs/item-umbrella-audit.json`, refreshed with `--output` by whichever change moves a coverage answer and held to a fresh run by `--check` (and by `tests/test_item_umbrella_audit.py`), so the published receipt cannot drift behind the code while its counts stay green.
- `champions/<name>.py` is the authoritative home for a champion's parser, slot map, options, assumptions, source receipts, five-slot coverage, review status, and declared cast dependencies. `champions/module_contract.py` validates that contract before the registry, API, or audits consume it. `packet_module.py` is only a champion-agnostic compiler; named modules pass their own timing and parser exceptions and pin the SHA-256 of the reviewed packet declaration they accept. Evidence drift therefore fails closed at import instead of silently changing formulas.
- `champions/healing_contract.py` defines the typed self-healing declaration owned by a champion module. `healing.py` loads those declarations and owns receipt ordering. A declaration without its own resolver (every rule but Aatrox's today) resolves through `healing_legacy._legacy_derive_self_healing`, the per-champion formula body. What a rule pays on — a cast, a hit that dealt damage, or a tick schedule of its own — is declared by the rule (`healing_legacy.HealAnchor`) and resolved by `healing_legacy._payments`; it is never inferred from how many events a module authored for the ability. A migrated rule provides its resolver from `champions/<name>.py`.
- `roster_composition.py` owns the `Combatant` value object, loadout conversion, main and actor parameter construction, target override signatures, roster window validation, and Catalyst resource inputs. `participant_timeline.py` keeps the event enrichment and survival orchestration that consumes those inputs.
- `loadout_rules.py` validates inventory capacity, boot tiers, duplicate items, and mutually exclusive item groups for both manual builds and optimization.
- `shield_ledger.py` owns what a damage instance does to a defender: timed-grant expiry, typed-pool consumption, Lifeline arming, general-pool consumption, health damage, overkill, and every absorbed total. All three absorption paths — both ordered walks in `damage.py` and the one survival kernel (`survival/transitions.py`) that the receipt and compiled-score compositions both run — call `absorb()` over a `ShieldPools`; they differ only in where that object is stored. Shields enter through `grant()` so a pool total and its expiry sub-ledger can never disagree, and defenses become pools through the one `build_pools()`, so the one-pair engine and the coupled ledger cannot stage the same item differently. Adding a shield mechanic or changing absorption order is one edit (issue #159).
- `defensive_effects.py` resolves defenses that are ready when combat begins. Starting shields, basic-damage modifiers, capped post-mitigation reductions, critical-strike reductions, and one-rotation threshold shields come from revision-backed Wiki mechanics. Timed threshold shields are priced from the certified event ledger; a timed fight with any uncertified damage source is withheld after computation, naming the coarse sources. Unregistered defenses remain explicitly outside the model.
- `ally_effects.py` compiles opt-in outgoing ally effects only when a sourced, tested rule exists.

## Combat model

`pipeline.py` validates ranks and request bounds, calculates stats, parses the selected champion, and calls the fight engine.

`damage.py` owns the fight state. It schedules casts, applies resource costs and regeneration, prices typed damage parts, updates mitigation, simulates auto attacks, and applies item effects. A shared ordered-damage ledger reconstructs accepted casts and exact typed row composition for threshold and shield consumers. Auto attacks carry their simulated per-swing times and damage; item effects without authored events remain explicitly coarse. Results include the accepted cast timeline, resource spent and remaining, per-source damage, TDD, health damage, shield absorption, and effective resistances.

The cast schedule is chronological. Some legacy damage layers still aggregate repeated casts by source after scheduling; those outputs must not be described as event-perfect until their mechanic has a dedicated timeline rule.

Cast *order* has two surfaces and they are deliberately separate. `cast_dependency.py` owns the declared vocabulary: what a champion module may assert about its own kit ("Scatter the Weak stuns only through a Dark Sphere her Q put on the field", so E requires Q), its four `DEPENDENCY_KINDS`, and the import-time validators the module contract runs. `rotation_resolver.py` owns inference — the twelve `INFERRED_EDGE_KINDS` it concludes from parsed markers — and the merge of declarations over inferences. The two vocabularies are closed and disjoint so an inferred classification can never be mistaken for a module's assertion. `cast_dependency.py` is a stdlib-only leaf: it imports nothing from `src/calculator`, which is what lets the resolver, the champion package and the pipeline share one vocabulary without the champion package owning the resolver's taxonomy. `champions/__init__.get_champion_cast_dependencies` is the one accessor; the validated contract is its only source.

## Scenarios

`scenario.py` resolves up to five enemies and four allies. Each roster card owns its champion, level, boots, items, item state, role, and quest state. Base health and bonus health remain separate.

The same selected damage package is evaluated against every selected enemy. Target-limited item procs are allocated once across the roster. Aggregate TDD is the sum of the resulting per-target damage, not a synthetic average target.

`participant_timeline.py` composes the per-pair event ledgers into one coupled survival walk. The authoritative transition kernel is in `survival/`. Reactive strike-back items (`item_effects.thorns_effects`) live in the timeline composition layer: each modeled basic attack that strikes a wearer schedules mitigated return damage and a Grievous Wounds window onto the striker, linked to the triggering event so retaliation dies with a skipped strike. In a fight with no incoming attacks, a thorns item correctly contributes nothing.

## Optimization

`optimizer.py` scores legal builds through the same `run_fight` pipeline used by manual calculations. The objective is modeled TDD unless the user explicitly selects physical or magic damage.

A one-item opening is searched exhaustively across modelled candidates. It is certified as best in slot only when candidate coverage is complete. If any available candidate is withheld, the result is labelled a certified subset (`bis_certified_subset_not_exhaustive`) and includes the excluded items and reasons. Complete builds use multi-start greedy search and hill climbing and are never labelled certified best in slot. The response includes the search guarantee, candidate-coverage receipt, build count, gold cost, and a distinct runner-up. Build A and Build B may never be identical.

The gold-constrained purchase search (`optimize_purchase`) fills the empty inventory slots with the available gold. Every plan is priced by `economy.py`'s real shop model — list-price buys with component credit, explicit combine fees, the sourced 70% sell table — and scored on its resolved final loadout. It mirrors `optimize_build`'s exact-versus-local duality: a priced depth-first walk first enumerates the affordable plan space, and when it fits under the candidate cap every plan is scored and the winner is certified (`exhaustive_purchase_scope`); a larger space falls back to a budget-aware local search — greedy fill by marginal damage and by marginal damage per gold, then hill climbing with a leftover-gold respend pass — labelled `purchase_local_search`. The guarantee is a label on an applied plan, never a reason to withhold the result.

Coupled searches score thousands of candidates against one fixed roster, so per-search caches reuse everything a candidate swap cannot change: roster-to-roster pair fights always, fights into the candidate whenever its defensive signature repeats (`participant_timeline._target_overrides` is both the engine contract and the cache key), pre-enriched pair event packets carrying precomputed survival-walk sort keys and once-compiled typed actions the receipt composition reuses across evaluations (issue #169), and a score memo for exactly repeated ordered builds that replays the recorded ordering-audit contribution. Candidate evaluation asks `build_participant_timeline` for the score-only receipt (`include_receipt=False`) — identical numbers, no public serialization.

Scoring additionally runs through a per-search `CoupledSearchContext`: every event compiles once into a flat walk action (sort key, participant indices, trigger slot, pre-resolved Grievous pack, heal category), the signature-independent roster fights — including a roster holder's active Warmog's Heart ticks — compile once per search, the fights into each distinct candidate defensive signature compile once per signature, and an evaluation then compiles only the main champion's fresh outgoing fights before running a no-copy survival walk with the same arithmetic, operation order, and rounding as the receipt walk — per-attacker sums replay the legacy list order so float addition cannot drift, and every pair fight carries the same roster-target allocation the receipt composition sets. A transition the compiler cannot stage fails closed onto the receipt walk with a named receipt; nothing is silently dropped. The engine supports this with caller-owned claims on `run_fight` (`validated`, `precomputed_stats`, `score_only`): score mode skips only provably-unread outputs (the one-pair shield outcome unless Protoplasm or a takedown-scanning support item needs it, display splits, per-cast resource receipt rows), and a champion with no self-heal rules (`healing.HEALING_RULE_CHAMPIONS`) and no heal-, execute-, or event-scan-relevant items returns its event ledger as light tuples instead of dict rows — the tuple predicate owns that item knowledge, so score-only rows always carry every field that prices a heal, a support packet, or an execute. Pure cached-JSON derivations (item stat blocks, ability leveling lookups, cast-time and resource-cost stamps) are memoized by object identity and re-verified on every hit so a data refresh can never serve stale values. The walk itself follows the same discipline (the sub-2s pass on issue #169's branch): the transition context precomputes ledger capability flags and per-subject defense profiles, participant states clone an identity-memoized prototype, and every hot-path shortcut — bare-health absorption, empty-ledger expiries, unarmed-modifier skips — is bit-identical to the full path it bypasses.

None of this changes which builds are evaluated or how they score: cache-vs-no-cache and compiled-walk-vs-receipt-walk equivalence are pinned by regression tests (`tests/test_participant_timeline.py`, `tests/test_optimizer.py`), and `scripts/bench_coupled_optimizer.py` reports the reference scenarios' builds, scores, and evaluation counts for manual comparison across changes.

## Public boundary

`app.py` is the HTTP adapter: it decodes JSON, applies cache/rate policy, delegates, translates typed failures, and serializes stable JSON. `request_parsing.py` owns the public scalar/list coercion policy; `calculate.py` owns the pure calculate payload and comparison-curve orchestration; `bis.py` owns candidate construction, scoring, ranking, and receipts; `certainty.py` and `validation_receipts.py` own trust and observed-result classification. Validation receipts call `calculate_payload()` directly, never round-trip through a Flask `Response` (issue #158).

`static/js/app.js` renders the scenario and results from backend receipts only: it contains no champion or item formulas, no item-id literals, and no local damage/stat engine (issue #135 retired the duplicate in-browser engine and the 175% crit fallback). Stat cards are fed by `POST /api/loadout-stats`; scores, breakdowns, BIS, and both optimizers consume `/api/calculate`, `/api/bis`, and `/api/optimize`. All three fight-scoring endpoints share one payload builder (`engineFightPayload`), which requests `time_based` — the engine's shared cast schedule, where an ability recasts whenever its cooldown is up inside the configured window — for every champion whose module certifies it; the few one-rotation-only modules fall back to `one_rotation` with their sourced reason surfaced in the Window constraint (`/api/champions` publishes `supported_fight_modes`).

Validated named champion modules are the only attacker path. Every cached champion can be used as an ally or target for independently derived base and item stats. Unknown attackers fail closed; there is no generic or fallback parser. Missing ally or defensive mechanics are disclosed as unmodeled context.

## Verification

- `pytest` covers calculations and API contracts.
- `pylint` enforces source quality.
- `scripts/golden_snapshot.py` detects numerical drift across full-pipeline scenarios.
- `scripts/coverage_census.py` sweeps every champion × fight mode, legally slotted item × window, keystone, and certified-item × enemy cell through the real payload boundaries; `docs/coverage-census.json` pins the residual coarse frontier and `docs/coverage-residue.json` acknowledges each pair with its cached sentence — an entry no row acknowledges and a row that no longer reproduces both fail. CI's `coverage-census` job checks the receipt; `patch_update.py run` refreshes it.
- browser verification covers empty start, selection, level changes, roster builds, A/B comparison, optimization, sharing, the single committed look (the dark/light toggle is retired — see `docs/redesign/gap-ledger.md` decision 3), and responsive layout.

Expected numerical changes require a sourced explanation and a reviewed golden-baseline update.
