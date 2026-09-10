# Architecture

The calculator separates sourced data, combat rules, scenario composition, optimization, and presentation. A value or rule should have one owner.

## Request path

```text
League Wiki cache
  -> data_fetcher.py
  -> scenario.py / stats.py
  -> champions/* + item_effects.py + rune_effects.py
  -> pipeline.py
  -> damage.py -> fight/                                 (one pair)
  -> participant_timeline.py -> program/ -> survival/     (roster)
  -> app.py
  -> app.js
```

`src/calculator/data_updater.py` and the rune pull it owns, `rune_pull.py`, are the only writers of the tracked runtime caches (champions/items/runes.json), and only through the atomic `data_registry.write_runtime_cache` API; `data_fetcher.py` is read-only. Every writer under `data/` addresses it by a repo-anchored path, never a cwd-relative literal, enforced by tests/test_data_writer_inventory.py. `patch_identity.py` maps a Riot public patch label to its client and source-version labels. `item_source.py` owns what the cache records about an item's sources, see below.

## Rules and ownership

- `stats.py` composes a champion's stat block: level growth through `stat_formulas.py` and `champion_growth.py`, item stats through `item_stat_block.py`, role-quest modifiers, and external ally stat effects. `resolve_pre_combat_stats` is the one composition every participant's pre-combat stat block resolves through, and `FightParams.pre_combat_stats` is the one read of a request into it. All five inputs are required keywords, so no surface can drop one by omission.
- `resistance.py` owns armor, magic resistance, and penetration order.
- `item_effects.py` owns item values and effect formulas. Item-specific numbers do not belong in routes or the interface.
- `rune_effects.py` owns rune values and effect formulas the same way, reading `data/runes.json` (parsed from the wiki's rune data templates by `rune_parser.py`). It is the public surface over one vocabulary shared by the whole page, holding resolve, validate, catalog and the effect types every compiler produces; every compiler lives under `rune_paths/`: keystones in `rune_paths/keystones.py`, minor runes in one module per path, and stat shards in `rune_paths/shards.py`. `validate_rune_page` enforces the page's rules (one rune per row, three from the primary path and two from a second, the keystone's path as the primary) and names the rule it refused on. Only compiled runes are selectable; the rest are served greyed out and fail closed if requested. A rune needing an input the request does not carry declares it as an option with a disclosed default, never an inferred constant.
- `item_behavior.py` is the closed vocabulary a mechanic is declared in: a frozen `BehaviorRule`, one of eighteen `RuleFamily` shapes, holding its numbers as `value_ref.ValueRef` references, its provenance as a receipt, and its legal-zero story declared rather than assumed. `DefenseMechanic` names each defensive source the same way (Guardian's Horn's Undaunted is one). `item_behavior_catalog.py` holds shapes and no float: the tag→family, `DefenseMechanic`→family and `ACTION_KIND_FAMILY` maps, and the per-family compilers that build declarations fresh from the live registries. All three maps are total, checked by `validate_catalog` at import, so a new effect tag, `ActionKind`, or `DefenseMechanic` fails collection until somebody decides its family.
- `value_ref.py` resolves a declaration's numbers at call time (spelled in `reference_vocabulary.py`, cited through `value_source_receipt.py`) against the three registries that own them (`ITEM_EFFECTS`, `ALLY_ITEM_EFFECTS`, `RUNE_EFFECTS`) through their own fail-loud accessors, so a declaration never holds a copied float.
- `interpreters/` runs those declarations: one interpreter per family per engine lane, emitting `KernelField`s at build time so nothing under `survival/` imports it. `compilability_for(owner, scope)` refuses to call an owner compilable while any of its rules is receipt-only in that scope, `uncompilable_item_receipt` names the refusal, and `reachability_report` names both a declaration no interpreter reaches and a branch no declaration reaches.
- `trigger_stream.py` is the one typed event bus: `event_triggers` is the only place a raw event row is classified, and `CAPABILITIES` is the only place a mechanic declares which streams it consumes. Every adequacy set the pipeline and the timeline consult is a projection of that declaration, never a second name list.
- `item_source.py` owns the ingested-source view of an item, folded from the two sources by `item_source_merge.py`: the complete branch list of every passive and active, map/mode availability, champion-granted and acquisition state, and the audit that reconciles the Wiki item table against Riot's description. Selection pools ask it whether an item is an ordinary Summoner's Rift purchase; nothing decides that from a name list. A source divergence is either a reviewed entry in `ACKNOWLEDGED_SOURCE_CONFLICTS` or it stops patch day. Neither source is silently preferred.
- `item_coverage.py` classifies each optimizer candidate as modelled, reviewed stats-only, blocked, or pending review. New passive or active text fails closed until it is explicitly classified. It answers whether a mechanic is *modelled*; `item_source.py` answers whether it was *ingested*. Every claim it makes carries typed evidence from `coverage_evidence.py`, whose load gate catches a claim that no evidence could back; whether the evidence resolves against the real tree is `tests/coverage_resolver.py`'s question.
- Full-entry source review is mandatory: every in-scope item and champion is checked against its complete League Wiki parent page before promotion. The exact receipt, effect inventory, module-slot coverage, hashes, and runtime reason are produced by `scripts/full_entry_audit.py`; see `docs/full-wiki-entry-review-requirement.md`.
- The item umbrella gate is separate from page review: `scripts/item_umbrella_audit.py` checks every classic-SR source record for explicit attacker and target coverage, compares manual/roster/optimizer pools, and fails on review-pending, unexplained, or unresolved source conflicts. Its receipt is `docs/item-umbrella-audit.json`, refreshed with `--output` by whichever change moves a coverage answer and held to a fresh run by `--check` (and by `tests/test_item_umbrella_audit.py`), so the published receipt cannot drift behind the code while its counts stay green.
- `champions/<name>.py` is the authoritative home for a champion's parser, slot map, options, assumptions, source receipts, and declared cast dependencies. `champions/module_contract.py` validates that contract before the registry, API, or audits consume it, in the coverage words `contract_vocabulary.py` owns and over the declaration sites `module_survey.py` reads; it derives the five-slot coverage from `SLOTS` unless the module declares `MODULE_COVERAGE`, and owns the one review status (every registered module is reviewed). `packet_module.py` is only a champion-agnostic compiler, over the reviewed-packet asset and slot parsers of `packet_parsers.py`; named modules pass their own timing, slot overrides (`slot_parsers` / `slot_wrappers` / `slot_order`) and `MODULE_CC` into that one call and keep the parser it returns, and pin the SHA-256 of the reviewed packet declaration they accept. The compiler stamps the accepted spec and digest on the parser; the contract reads the pin off that stamp, surveys the module's `PACKET_SHA256` against it, and refuses a module whose running parser carries no stamp, so evidence drift and a rebound parser both fail closed at import instead of silently changing formulas. `MODULE_CC` is the one crowd-control declaration (`{slot: kind}`, `"none"` = reviewed no-CC); a sourced control duration rides the slot through `slot_control.with_control` / `with_control_event`, whose kind must agree with the declaration. Scope rides only `with_control_event` and `park_control_interval`, where a targeted cast names `control_spec.ControlScope.ONE_TARGET` and is allocated to the roster's first defender the way a target-limited item proc is; `with_control` takes no scope, so a control attached to a damaging slot reaches every enemy the cast hit. `ULTIMATE_RECASTS` is the one place a module lifts the timed scheduler's cast-R-once rule: absent (the default) an ultimate casts once whatever its cooldown, because a form, stance, charge pool or escalating cost the engine does not simulate is not safe to repeat; declared, R recasts on its hasted cooldown and ultimate haste finally moves the number.
- `champions/healing_contract.py` defines the typed self-healing declaration owned by a champion module, and each champion module owns its `derive_self_healing` resolver and formula. `healing_helpers.py` owns what those resolvers share: the sourced readers and the payment anchors. What a rule pays on (a cast, a hit that dealt damage, or a tick schedule of its own) is declared by the rule (`HealAnchor`) and never inferred from how many events a module authored. `healing.py` loads declarations, derives `HEALING_RULE_CHAMPIONS` from the modules that export one, and owns generic healing application and receipt ordering. Champion-option state a heal needs (`self_heal_state`, `self_heal_share_of_damage`) is priced in the module entry, where both the options and the target are in hand.
- `roster_composition.py` owns the `Combatant` value object, loadout conversion, main and actor parameter construction, target override signatures, roster window validation, and Catalyst resource inputs. `participant_timeline.py` keeps the event enrichment and survival orchestration that consumes those inputs.
- `loadout_rules.py` validates inventory capacity, boot tiers, duplicate items, and mutually exclusive item groups for both manual builds and optimization.
- `shield_ledger.py` owns what a damage instance does to a defender: timed-grant expiry, typed-pool consumption, Lifeline arming, general-pool consumption, health damage, overkill, and every absorbed total. All three absorption paths, the two ordered walks (`fight/ledger/pool_walk.py` and `fight/after/shield_outcome.py`) and the one survival kernel (`survival/transitions.py`) that the receipt and compiled-score compositions both run, call `absorb()` over a `ShieldPools`; they differ only in where that object is stored. Shields enter through `grant()` so a pool total and its expiry sub-ledger can never disagree, and defenses become pools through the one `shield_pools.build_pools()`, so the one-pair engine and the coupled ledger cannot stage the same item differently. Adding a shield mechanic or changing absorption order is one edit (issue #159).
- `defensive_effects.py` resolves defenses that are ready when combat begins, over the state and ledger `starting_defenses.py` holds and the champion's own openers in `champion_opening_defenses.py`. Starting shields, basic-damage modifiers, capped post-mitigation reductions, critical-strike reductions, and one-rotation threshold shields come from revision-backed Wiki mechanics. Timed threshold shields are priced from the certified event ledger; a timed fight with any uncertified damage source is withheld after computation, naming the coarse sources. Unregistered defenses remain explicitly outside the model.
- `ally_effects.py` compiles opt-in outgoing ally effects only when a sourced, tested rule exists.

Nine dependency-light leaves own the typed contracts shared mechanics need. Each takes its numbers from a consumer's typed accessor, attaches a source receipt, and fails closed with a named reason rather than inventing a value:

| leaf | owns |
|---|---|
| `state_lifecycle.py` | trigger predicates, cooldowns, charge pools, lockouts and resets, over the deterministic transition order `state_timeline.py` records; stack gain/loss, caps, durations, expiry and refresh are declared in `stack_rules.py`, driven in `timed_stacks.py` and gated in `window_gates.py` |
| `resource_ledger.py` | one MANA account per participant: gain, spend, refund, regeneration, caps, same-time order, ownership, receipts, in the event vocabulary `resource_events.py` holds. Manaflow is `manaflow_ledger.py` and the two sourced item schedules are `mana_item_schedules.py`. Any other kind is refused: an account maximum grows and never falls, so the temporary maximum an energy kit declares (Akali's W) has no representation here; `fight/rotation/energy_walk.py` admits energy casts against a plain clamped pool on the same skeleton instead |
| `delivery_eligibility.py` | which defense accepts which delivery class, over the packet records of `delivery_facts.py` and the six classes of `delivery_classes.py`; what happens to an accepted event is `defense_composition.py`, and the spell shield's own lifecycle is `spell_shield_eligibility.py` with the re-arm clock in `spell_shield_rearm.py` |
| `crowd_control_eligibility.py` | control classification, blocking versus soft kinds, and Black-Shield-style immunity windows |
| `cleanse_eligibility.py` | item cleanses (Mikael's Purify, Quicksilver Sash and Mercurial Scimitar) and the action-downtime truncation they cause, over the tooltips of `cleanse_declarations.py` and `champion_cleanses.py` and the span algebra of `control_intervals.py` |
| `interaction_effects.py` | champion-to-champion interaction atoms: their timing, selection, and one-use rules, held apart from damage arithmetic. The readers all three price from are `interaction_atoms.py`; the projectile defence is `projectile_defense.py` |
| `spatial.py` | position extraction, Euclidean distance, and holder-centered range counting |
| `ability_atoms.py` | strict typed-atom access into the cached champion ability rows |
| `ledger_projection.py` | which narrowing of a pair fight's result its readers can still be served: each clause is an `AdequacyCondition` naming its reader, declared in `ledger_declarations.py` and probed in `ledger_adequacy.py` over the typed facts of `ledger_inputs.py`, and `pipeline.run_fight` and `damage.calculate_fight_damage` read the answer here instead of holding a conjunction each |

Three more leaves carry code the tree shares without a receipt of their own:

| leaf | owns |
|---|---|
| `stat_formulas.py` | the game's own stat formulas: growth, attack speed and its cap, movement-speed soft caps, and cooldown from ability haste |
| `ability_prose.py` | the numbers a cached ability states in a sentence instead of a leveling row |
| `champions/slot_context.py` | what a slot parser is handed (`SlotCtx`) and the phases it runs in |

Each owner above resolves to one file per idea. These are the leaves they hold:

| leaf | owns |
|---|---|
| `capability_fields.py` | one public field descriptor per loadout, scenario and feature control the browser mounts |
| `atom_spelling.py` | how a cached name and stat field are spelled in the atom contract |
| `atomizer_abilities.py` | the atomizer's ability domain: champion slot to effect to leveling modifier |
| `item_source_merge.py` | how patch ingestion folds the Wiki item table and Riot's description into one cached entry |
| `vendor_path.py` | the vendored lolstaticdata checkout, on the import path and imported once |
| `wiki_fetch.py` | one HTTP fetch of a wiki page: a finite wait and an explicit HTTP error |
| `rune_pull.py` | the wiki rune-template pull and the reparse of the cached rune effects |
| `reference_vocabulary.py` | the closed vocabularies a value reference is spelled in, and the refusal any of them raises |
| `value_source_receipt.py` | the revision a declaration's numbers were read from, and the registry entry it is cited from |
| `item_stat_block.py` | what a cached item row's stat block is, validated once per data generation |
| `champion_growth.py` | a champion's base stat block at a level |
| `starting_defenses.py` | the defensive state a fight starts with, the citation each source publishes, and their ledger |
| `champion_opening_defenses.py` | the defences a champion's kit has up before the first cast |
| `ledger_inputs.py` | the narrowed result row and the typed facts a projection decision reads |
| `ledger_declarations.py` | what each adequacy condition demands of a build, and which reader serves it |
| `ledger_adequacy.py` | which owner holds a mechanic: one probe per declared condition |
| `shield_pools.py` | the pools a participant carries, the shields granted into them, and when each expires |
| `state_timeline.py` | the transition record a declaration cites: the receipt, the stamp, and the timeline that orders them |
| `stack_rules.py` | how a stack is gained, refreshed, capped and expired, as one declaration |
| `timed_stacks.py` | the timed stack state a stack rule drives |
| `window_gates.py` | the window stack gate, its two hit pair and its per-target cooldown |
| `resource_events.py` | the mana event vocabulary: the operations a row states, their tiers, and each one's receipt |
| `manaflow_ledger.py` | Manaflow: one named passive, two trigger streams, one charge pool |
| `mana_item_schedules.py` | Lost Chapter's Enlighten and Catalyst's Eternity, built on the account's receipts |
| `interaction_atoms.py` | the ranked atom and prose duration readers every interaction prices from |
| `projectile_defense.py` | one champion-to-champion interaction with its own eligibility, composition and public shape |
| `program/tagged.py` | a number and the view it was produced for, and the one way tagged numbers fold |
| `program/capability.py` | what each declared mechanic's engine lanes say a view may show |
| `program/sums.py` | which panel rows a published total counts, and in what order |
| `program/views/view_tag.py` | whether a published number was delivered or previewed |
| `program/views/dispositions.py` | what a serving surface may rank, read back off a published disposition map |
| `program/views/leaf.py` | where every leaf the five views publish is born, and the writers that collect them |
| `program/views/survival_blocks.py` | the state blocks a survival row publishes only when the state has them |
| `survival/receipt_ledger.py` | the receipt ledger a walk writes its outcomes into |
| `survival/defense_contracts.py` | the one place the four interaction resolvers are read into a participant state |
| `survival/phases.py` | when a transition resolves, and what the public timeline calls that phase |
| `survival/event_slots.py` | the kernel's four event references as integers |
| `survival/typed_action.py` | the typed action the walk consumes: its kind, its live amplification, its trigger linkage |
| `survival/classify.py` | what an event is: its damage and attack class, the modifier classes it declares, and its rank |
| `src/beta_gate.py` | the four weekly criteria the beta contract sets, and the windows they are measured over |
| `delivery_facts.py` | one packet, its combatants, a defense's armed window, and `stable_event_key` |
| `delivery_classes.py` | the six classes a delivery is declared as, and how one action is classified into them |
| `defense_composition.py` | what happens to an event a defense accepted: uses, full block, destruction, reduction |
| `spell_shield_rearm.py` | the spell shield's re-arm clock, and the sourced rule it runs on |
| `spell_shield_eligibility.py` | which cast a spell shield blocks, and what the block does |
| `cleanse_declarations.py` | the sourced item cleanse tooltips, one declaration per item, and the lookup over them |
| `champion_cleanses.py` | the sourced champion abilities that remove control |
| `control_intervals.py` | span algebra over control and downtime intervals |
| `interpreters/damage_deferral.py` | the post-mitigation damage a deferral stores and repays as ticks |
| `interpreters/rearmed_swings.py` | when a rearmed swing lands, and the two re-ratings one attack stream merges |
| `interpreters/amp_magnitude.py` | how a declared amp magnitude becomes a fraction, and the fields it compiles to |
| `interpreters/part_amp.py` | the amps that multiply one damage part rather than a chain slot |
| `champions/entry_shape.py` | every key an emitted entry may carry, and the refusal for one it may not |
| `champions/slot_cc.py` | the module's crowd-control declaration, stamped onto the parts a slot emits |
| `champions/slot_extract.py` | the one `effects[].leveling[].modifiers[]` walk |
| `champions/slot_entries.py` | the entry dicts a slot parser hands the fight engine |
| `champions/slot_control.py` | a control atom, and the archetypes that attach one to a slot |
| `champions/contract_vocabulary.py` | the coverage words a champion module declares, and the contract they read into |
| `champions/module_survey.py` | each contract fact read off a module's three declaration sites, and the refusal for a malformed one |
| `champions/packet_parsers.py` | the reviewed-packet asset, and the slot parser one of its rows compiles to |
| `champions/renata_bailout_authority.py` | the field-by-field source adjudication that keeps Bailout's lethal half withheld |
| `champions/aurelion_sol_stardust.py` | the Stardust stack pool, and what a Q burst and an E execute are worth per stack |
| `champions/aphelios_weapons.py` | which of the five weapons is in hand, what each adds on hit, and the Weapon Master points |
| `quantity.py` | what a published number is: measured, a structural zero, withheld, or starved |
| `control_spec.py` | the one crowd-control vocabulary, its three partitions, and the control event a cast carries |
| `fight_request_bounds.py` | what a public fight request may say, and the readers that coerce it |
| `fight_params.py` | the parsed fight request: every field one fight is run with |
| `item_sustain_events.py` | the healing an item did, read back off a finished fight result |
| `rune_sustain_events.py` | the healing a rune page did, read back off a finished fight result |
| `fight_receipts.py` | the receipts and display splits attached to a finished fight |
| `champion_loadout.py` | one roster card, and what resolving it produces |
| `ability_ranks.py` | how many ranks a kit authored, and the ranks a roster card may ask for at a level |
| `ally_packet_shape.py` | what one cross-participant item packet is, the producer it came from, and the authority it is audited against |
| `ally_packet_recipient.py` | re-pricing a one-ally packet for the ally actually selected |
| `support_event_view.py` | the fight-result streams a support packet is priced from, and the refusal when the view is starved |
| `support_scan.py` | which champion slots the cached rows say heal or shield an ally, and the profile that answer folds into |
| `support_row_metadata.py` | what one support row publishes: recipient scaling, rank, duration and timing |
| `support_bailout.py` | Renata Glasc's Bailout: its ramp, its denial rows and the shape it withholds |
| `support_champion_packets.py` | the sourced per-champion metadata and follow-up packets an ally receives |
| `self_state_effects.py` | the self state windows a champion module authors, expanded over its accepted cast times |
| `optimizer_candidates.py` | which items a search may legally hold, and what they cost |
| `build_evaluation.py` | scoring one candidate build through the same `run_fight` the manual path uses |
| `build_receipts.py` | what an evaluated build publishes |
| `build_search.py` | greedy fill and hill climbing over legendary slots |
| `purchase_plans.py` | the gold-constrained plan space: what one plan is, how it is enumerated and priced, and the two searches over it |
| `purchase_search.py` | `optimize_purchase`, the one gold-budget search the API calls |
| `bis_candidates.py` | which items a BIS search ranks, for which subject, in which order |
| `bis_objective.py` | what BIS optimises for, and how one candidate folds into that number |
| `cast_order_overrides.py` | the champions whose cast order is asserted by hand, and the reason each one is |
| `cast_edge_markers.py` | the parsed-text markers and slot corpus a cast edge or an AoE cap is read out of |
| `cast_edge_inference.py` | the twelve edge kinds inferred from a champion's own rows |
| `cast_edge_resolution.py` | declared edges merged over inferred ones, and the topological order they admit |
| `ability_dps_matrix.py` | the per-champion level-by-build DPS matrix, and the ability ranking read off it |
| `champion_rotation_rule.py` | the `ComboRule` fitted to one fight from a champion's DPS matrix |

## Combat model

`pipeline.py` validates ranks and request bounds, calculates stats, parses the selected champion, and calls the fight engine.

`damage.py` orchestrates the fight. `calculate_fight_damage` calls the steps of the `fight/` package in the order they run, and each subpackage is one step: `fight/setup/` resolves resistances, amps and attack timing into a `FightState`; `fight/rotation/` schedules casts, admits them against the resource walk, and prices each cast's typed parts; `fight/autos/` owns the swing schedule and everything that rides a basic attack; `fight/items/` and `fight/runes/` price the packets neither of those authors; `fight/stacks/` walks one champion stack resource per module as a receipt ledger; `fight/ledger/` reconstructs the ordered damage ledger and walks the target's pools over it; `fight/after/` applies the amplifiers, the repricing and the shield split over the finished ledger. The vocabulary every step reads is directly under `fight/`: `config.py`, `state.py`, `declarations.py`, `results.py`, `resists.py`, `mitigation.py`, `cast_slots.py`, `empower_declaration.py` and `cast_control_marker.py`. Each `__init__.py` holds one docstring line and no re-export, so a reader opens the step and not the package.

Inside `fight/autos/` a strike is filed by what fires it: `on_hit_layering.py` pays the effects every hit carries, `first_auto_strikes.py` the strikes that spend a charge on one swing, `stacking_strikes.py` the strikes a counter of landed hits fires, and `spellblade.py` the charge a cast arms. `fight/items/secondary_delivery.py` is the one home for a packet that lands on a subject the attack was not aimed at: Wind's Fury bolts, a Cleave splash, a chained strike's arc. No step in `fight/` spells a cached item name outside the five entries `tests/test_architecture.py` lists with the reason each is still there. Of the three deliveries only the bolt reads its row key, row name and targeting kind off the declared `SecondaryTargetRule`; the Cleave splash and the max-health cone still resolve their holder by asking `item_effects` which held item carries the effect keys, and `loadout_rules`'s `Hydra` exclusivity group is what keeps that question single-answered.

`fight/ledger/trace.py` derives one line per priced packet from a finished fight: time, source, mechanic, raw, damage class, the resistance it met, the amplifier pool, the mitigated amount and the step that wrote it, with a named refusal wherever the fight stated no value. It runs no arithmetic of the engine's; the step column is measured by `fight/authorship.py`, whose recording `dict` stamps the writing frame onto every breakdown row while `authorship.recording()` is armed and costs nothing when it is not. `scripts/fight_trace.py` prints or captures it from a request JSON.

The ordered damage ledger reconstructs accepted casts and exact typed row composition for threshold and shield consumers. Auto attacks carry their simulated per-swing times and damage; item effects without authored events remain explicitly coarse. Results include the accepted cast timeline, resource spent and remaining, per-source damage, TDD, health damage, shield absorption, and effective resistances.

The cast schedule is chronological. Some legacy damage layers still aggregate repeated casts by source after scheduling; those outputs must not be described as event-perfect until their mechanic has a dedicated timeline rule.

Cast *order* has two surfaces and they are deliberately separate. `cast_dependency.py` owns the declared vocabulary: what a champion module may assert about its own kit ("Scatter the Weak stuns only through a Dark Sphere her Q put on the field", so E requires Q), its four `DEPENDENCY_KINDS`, and the import-time validators the module contract runs. `rotation_resolver.py` owns inference, the twelve `INFERRED_EDGE_KINDS` it concludes from parsed markers, and the merge of declarations over inferences. The two vocabularies are closed and disjoint so an inferred classification can never be mistaken for a module's assertion. `cast_dependency.py` is a stdlib-only leaf: it imports nothing from `src/calculator`, which is what lets the resolver, the champion package and the pipeline share one vocabulary without the champion package owning the resolver's taxonomy. `champions/__init__.get_champion_cast_dependencies` is the one accessor; the validated contract is its only source.

## Scenarios

`scenario.py` resolves up to five enemies and four allies. Each roster card owns its champion, level, boots, items, item state, role, and quest state. Base health and bonus health remain separate.

The same selected damage package is evaluated against every selected enemy. Target-limited item procs are allocated once across the roster. Aggregate TDD is the sum of the resulting per-target damage, not a synthetic average target.

`participant_timeline.py` composes the roster, per-pair event ledgers, and one coupled survival walk, and owns `CoupledSearchContext`, the per-search compile-once caches. `program/` is the logical layer above the kernel, "what happened, and to whom": `events.py` closes what a packet may be (`PairEvent` before routing, `RoutedEvent` after; a packet matching no family raises `UnclassifiedEvent`), `route.py` resolves each event's subject once and totally, `build.py` freezes the whole fight before any representation choice, `compile.py` holds `WalkCompiler` and the one `SurvivalAction` constructor, and `walk.py` is the one `run_survival_walk` call site, returning a frozen `WalkResult`. `program/views/` holds its five projections (`receipt`, `score`, `survival`, `breakdown`, `tdd`); a view re-runs no arithmetic, every number it emits is already a leaf of the result, and takes every digit count from `program/precision.py`, which is where rounding lives. `survival/` is the transition kernel underneath: `actions`, `transitions` (the walk and its dispatch ladder), `receipt_state`, `score_state`, `compile`, `pricing`, `accumulate`. The dependency runs `program -> survival` and never back, so the hot loop never dispatches on a logical type.

Reactive strike-back items (`interpreters.reactive.thorns_effects`) live in the timeline composition layer: each modeled basic attack that strikes a wearer schedules mitigated return damage and a Grievous Wounds window onto the striker, linked to the triggering event so retaliation dies with a skipped strike. In a fight with no incoming attacks, a thorns item correctly contributes nothing.

## Optimization

`optimizer.py` scores legal builds through the same `run_fight` pipeline used by manual calculations. The objective is modeled TDD unless the user explicitly selects physical or magic damage.

A one-item opening is searched exhaustively across modelled candidates. It is certified as best in slot only when candidate coverage is complete. If any available candidate is withheld, the result is labelled a certified subset (`bis_certified_subset_not_exhaustive`) and includes the excluded items and reasons. Complete builds use multi-start greedy search and hill climbing and are never labelled certified best in slot. The response includes the search guarantee, candidate-coverage receipt, build count, gold cost, and a distinct runner-up. Build A and Build B may never be identical.

The gold-constrained purchase search (`optimize_purchase`) fills the empty inventory slots with the available gold. Every plan is priced by `economy.py`'s real shop model, list-price buys with component credit, explicit combine fees and the sourced 70% sell table, and scored on its resolved final loadout. It mirrors `optimize_build`'s exact-versus-local duality: a priced depth-first walk first enumerates the affordable plan space, and when it fits under the candidate cap every plan is scored and the winner is certified (`exhaustive_purchase_scope`); a larger space falls back to a budget-aware local search labelled `purchase_local_search`: greedy fill by marginal damage and by marginal damage per gold, then hill climbing with a leftover-gold respend pass. The guarantee is a label on an applied plan, never a reason to withhold the result.

Coupled searches score thousands of candidates against one fixed roster, so per-search caches reuse everything a candidate swap cannot change: roster-to-roster pair fights always, fights into the candidate whenever its defensive signature repeats (`roster_composition.target_overrides` is both the engine contract and the cache key), pre-enriched pair event packets carrying precomputed survival-walk sort keys and once-compiled typed actions the receipt composition reuses across evaluations (issue #169), and a score memo for exactly repeated ordered builds that replays the recorded ordering-audit contribution. Candidate evaluation asks `build_participant_timeline` for the score-only receipt (`include_receipt=False`): identical numbers, no public serialization.

Scoring runs through a per-search `CoupledSearchContext`: every event compiles once into a flat walk action (sort key, participant indices, trigger slot, pre-resolved Grievous pack, heal category), the signature-independent roster fights, including a roster holder's active Warmog's Heart ticks, compile once per search, the fights into each distinct candidate defensive signature compile once per signature, and an evaluation then compiles only the main champion's fresh outgoing fights before the one walk runs with the same arithmetic, operation order, and rounding the receipt reads: per-attacker sums replay the legacy list order so float addition cannot drift, and every pair fight carries the same roster-target allocation the receipt composition sets. A transition the compiler cannot stage fails closed with a named `uncompilable_item_receipt`; nothing is silently dropped. The engine supports this with caller-owned claims on `run_fight` (`validated`, `precomputed_stats`, `score_only`): score mode skips only the outputs `ledger_projection` proves unread, and a champion with no self-heal rules and no heal-, execute-, or event-scan-relevant items returns its event ledger as light tuples instead of dict rows. Pure cached-JSON derivations (item stat blocks, ability leveling lookups, cast-time and resource-cost stamps) are memoized by object identity and re-verified on every hit so a data refresh can never serve stale values. The walk itself follows the same discipline (the sub-2s pass on issue #169's branch): the transition context precomputes ledger capability flags and per-subject defense profiles, participant states clone an identity-memoized prototype, and every hot-path shortcut, bare-health absorption, empty-ledger expiries and unarmed-modifier skips, is bit-identical to the full path it bypasses.

None of this changes which builds are evaluated or how they score: cache-vs-no-cache and compiled-walk-vs-receipt-walk equivalence are pinned by regression tests (`tests/test_participant_timeline.py`, `tests/test_optimizer.py`), and `scripts/bench_coupled_optimizer.py` reports the reference scenarios' builds, scores, and evaluation counts for manual comparison across changes.

## Public boundary

`ui/src/Calculator.tsx` owns the shared build-comparison interface. Its transport
accepts an API prefix, so the standalone Flask page and Scryglass's native
`/calculator` page use the same controls and response presentation. The standalone
bundle is built with `cd ui && npm ci && npm run build`. Scryglass imports the
reviewed source through `scripts/sync-calculator-ui.mjs`; its receipt binds each
shared file to a calculator commit. Changes to the shared interface start here.

The Scryglass server checks membership before its calculator proxy forwards an
allowlisted request. `src/service_auth.py` restricts the server credential to
catalog reads and calculation requests. The credential stays on the servers.
The Python pipeline remains the owner of all calculated numbers.

The standalone `/` route mounts the shared interface. `/advanced` retains the
complete roster workspace and its event inspectors. Existing `?share=` links
still open that workspace.

`app.py` is the HTTP adapter: it decodes JSON, applies cache/rate policy, delegates, translates typed failures, and serializes stable JSON. `request_parsing.py` owns the public scalar/list coercion policy; `calculate.py` owns the pure calculate payload, its comparison-curve orchestration, and the one-request deterministic Build A/Build B boundary (`compare_payload`); `bis.py` owns candidate construction, scoring, ranking, receipts, and the batch payload; `certainty.py` and `validation_receipts.py` own trust and observed-result classification. Validation receipts call `calculate_payload()` directly, never round-trip through a Flask `Response` (issue #158). `calculate_payload(..., trace=True)` is a keyword for a direct caller only: no request field reaches it, `request_parsing.py` coerces no such key, and the `trace` block is absent from every payload nobody asked for it on.

`capabilities.py` publishes the mounted control contract, every loadout, scenario, feature and catalog field the browser may render, each with a stable `frontend_token`, so a control is rendered only when the backend can consume its value, or disabled with an honest reason. `CAPABILITY_SCHEMA_VERSION` moves whenever a published shape does.

`static/js/app.js` renders the scenario and results from backend receipts only: it contains no champion or item formulas, no item-id literals, and no local damage/stat engine (issue #135 retired the duplicate in-browser engine and the 175% crit fallback). Stat cards are fed by `POST /api/loadout-stats`; scores, breakdowns, build comparison, BIS, and both optimizers consume `/api/loadout-stats`, `/api/calculate`, `/api/compare`, `/api/bis`, and `/api/optimize`. `/api/compare` returns two deterministic calculation receipts from one request, so a build comparison does not fan out into two browser requests. All fight-scoring paths share one payload builder (`engineFightPayload`), which requests `time_based`, the engine's shared cast schedule where an ability recasts whenever its cooldown is up inside the configured window, for every champion, or `auto_only` when the Autos-only constraint is set. Every registered module certifies every public fight mode, so the browser derives the mode from the constraints bar alone and never from the champion; `one_rotation` stays an engine mode the API accepts from a direct caller.

`static/js/scoreboard.js` reads a pasted scoreboard screenshot into a roster in the browser, matching every cell against the per-patch icon sprite `scripts/build_icon_sprite.py` writes, and hands the result to the shared-build loader; `tests/test_scoreboard_vision.py` holds it to the labeled frames in `tests/fixtures/scoreboard/`. See `docs/scoreboard-autofill.md`.

Validated named champion modules are the only attacker path. Every cached champion can be used as an ally or target for independently derived base and item stats. Unknown attackers fail closed; there is no generic or fallback parser. Missing ally or defensive mechanics are disclosed as unmodeled context.

## Verification

- `pytest` covers calculations and API contracts.
- `pylint` enforces source quality.
- `scripts/golden_snapshot.py` detects numerical drift across full-pipeline scenarios.
- `scripts/coverage_census.py` sweeps every champion × fight mode, legally slotted item × window, keystone, and certified-item × enemy cell through the real payload boundaries; `docs/coverage-census.json` pins the residual coarse frontier and `docs/coverage-residue.json` acknowledges each pair with its cached sentence. An entry no row acknowledges and a row that does not reproduce both fail. CI's `coverage-census` job checks the receipt; `patch_update.py run` refreshes it.
- `tests/test_program_structure.py` pins the layering: one `run_survival_walk` call site in `src/`, one `SurvivalAction` constructor outside the declared fast-path row, the one-way `program -> survival` import direction, view purity (no view nor anything it calls does arithmetic), and the allocation budget.
- browser verification covers empty start, selection, level changes, roster builds, A/B comparison, optimization, sharing, the single committed look (the dark/light toggle is retired, see `docs/redesign/gap-ledger.md` decision 3), and responsive layout.

Expected numerical changes require a sourced explanation and a reviewed golden-baseline update.
