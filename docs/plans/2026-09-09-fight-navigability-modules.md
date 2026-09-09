218 new modules across the 13 stages.

# Phase 27 new module roster

One table per stage. Names, meanings and definition lists come from the nine maps beside
`plan.md`. Where `plan.md` renames a map's module or settles a choice a map left open, the plan's
name is the one here.

## Stage 1, 2 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `tests/kernel_fixtures.py` | `tests/test_survival_kernel.py` | the holder, the fixture and the registry every kernel-equivalence suite is built from | 21 defs: `Holder`, `KernelFixture`, ... `_ally_survival` | 420 |
| `tests/support_effect_fixtures.py` | `tests/test_item_support_effects.py` | the actor, the grown registry and the declared packet vocabulary every item-support suite reads | 10 defs: `_capability`, `_grown_registry`, ... `timed_cross_participant_producers` | 160 |

## Stage 2, 12 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/capability_fields.py` | `src/calculator/capabilities.py` | one public field descriptor per loadout, scenario and feature control the browser mounts | `_field`, `_participant_fields`, `_feature_fields` | 340 |
| `src/beta_gate.py` | `src/metrics.py` | the four weekly criteria the beta success contract sets, and the windows they are measured over | 22 defs: `RETENTION_THRESHOLD`, `RECEIPTS_PER_WEEK`, ... `_weekly_gate` | 290 |
| `src/calculator/atomizer_abilities.py` | `src/calculator/atomizer_domains.py` | the ability domain: champion slot to effect to leveling modifier, plus the prose values a row states in a sentence | `_FOCUS_WINDOW_EFFECTS`, `_FOCUS_WINDOW_ACTIVE_EFFECTS`, `atomize_abilities` | 275 |
| `src/calculator/coverage_claim_gate.py` | `src/calculator/coverage_evidence.py` | the load gate: a claim, its status policy, and the refusal of a claim no evidence could back | 20 defs: `UTILITY_DIMENSIONS`, `CoverageClaimError`, ... `validate_claim_table` | 410 |
| `src/calculator/item_source_merge.py` | `src/calculator/item_source.py` | how patch ingestion folds the Wiki item table and Riot's description into one cached entry | 13 defs: `_PASSIVE_KEY_MARKERS`, `_ACTIVE_KEY_PREFIX`, ... `merge_item_sources` | 290 |
| `src/calculator/rune_pull.py` | `src/calculator/data_updater.py` | the wiki rune-template pull and the reparse of the cached rune effects | 15 defs: `_WIKI_API_URL`, `_RUNE_TEMPLATE_PREFIX`, ... `reparse_cached_rune_effects` | 255 |
| `src/calculator/source_receipt.py` | `src/calculator/value_ref.py` | the revision a declaration's numbers were read from, and how one is resolved | `SourceReceipt`, `_entry_receipt`, `receipt_for`, `UnsourcedDeclarationError` | 96 |
| `src/calculator/cast_order_request.py` | `src/calculator/cast_dependency.py` | what a user's custom cast order may say, expanded and checked against the declared dependencies | `orderable_slots`, `expand_user_order`, `check_order_satisfies_dependencies`, `CustomOrderViolatesDependencyError` | 110 |
| `src/calculator/item_stat_block.py` | `src/calculator/stats.py` | what a cached item row's stat block is, validated once per data generation | 9 defs: `_ONE_ITEM_STAT_TYPE`, `item_stat_type_count`, ... `item_mana_reaches_pool` | 200 |
| `src/calculator/champion_growth.py` | `src/calculator/stats.py` | a champion's base stat block at a level | `get_champion_base_stats` | 35 |
| `src/result_cache.py` | `src/db.py` | the request result cache: redis when configured, the `CachedResult` table otherwise, and the hit and miss counters | 17 defs: `_REDIS_ENTRY_PREFIX`, `_REDIS_COUNTER_KEY`, ... `cache_stats` | 240 |
| `src/user_records.py` | `src/db.py` | the rows a user action writes: saved builds, share links, validation feedback and metric events | 13 defs: `_BUILD_COLUMNS`, `_BUILD_TOP_LEVEL_KEYS`, ... `record_metric_event` | 420 |

## Stage 3, 4 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/starting_defenses.py` | `src/calculator/defensive_effects.py` | the defensive state a fight starts with, and how each source is cited | `DEFENSE_SOURCE_LABEL`, `DefenseCitation`, `defense_source`, `StartingDefenses` | 290 |
| `src/calculator/champion_opening_defenses.py` | `src/calculator/defensive_effects.py` | the defences a champion's own kit has up before the first cast | 8 defs: `_GALIO_SHIELD_MIN_PERCENT`, `_GALIO_SHIELD_MAX_PERCENT`, ... `_apply_champion_revive` | 95 |
| `src/calculator/ledger_inputs.py` | `src/calculator/ledger_projection.py` | the narrowed row, and the typed facts a projection decision reads | 11 defs: `ResultProjection`, `LightRow`, ... `LedgerInputs` | 180 |
| `src/calculator/ledger_adequacy.py` | `src/calculator/ledger_projection.py` | which owner holds this mechanic: the declaration table and the owner probes | 30 defs: eleven `_*_READER` constants, `_DECLARATIONS`, `DECLARATIONS`, sixteen `_*_owners` probes, `_held` | 360 |

## Stage 4, 14 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/program/folds.py` | `src/calculator/program/walk.py` | the leaves a composition folds once so no view adds | 7 defs: `AttackerOutcome`, `_crowd_control_immunity`, ... `ObjectiveFold` | 290 |
| `src/calculator/program/sums.py` | `src/calculator/program/precision.py` | which panel rows a published total counts, and in what order | `SUM_PANELS`, `DuplicateSumMember`, `SumPlan`, `sum_plan` | 150 |
| `src/calculator/program/views/survival_blocks.py` | `src/calculator/program/views/survival.py` | the state blocks a survival row publishes only when the state has them | `_optional_time`, `_combat_state_blocks`, `_rune_state_blocks`, `_cleanse_receipt`, `_CONDITIONAL_STATE_BLOCKS` | 130 |
| `src/calculator/program/views/dispositions.py` | `src/calculator/program/views/__init__.py` | what a serving surface may rank, read back off a published disposition map | `refuse_previewed`, `published_tag`, `published_quantity` | 110 |
| `src/calculator/program/views/leaf.py` | `src/calculator/program/views/__init__.py` | where every leaf the five views publish is born, and the writers that collect them | 8 defs: `LeafOut`, `serialize_leaf`, ... `name_every_number` | 340 |
| `src/calculator/program/tagged.py` | `src/calculator/program/build.py` | a number and the view it was produced for, and the one way tagged numbers fold | `MixedViewFold`, `Tagged`, `fold_tagged`, `ranked_total`, `tag_for` | 110 |
| `src/calculator/program/capability.py` | `src/calculator/program/build.py` | what each declared mechanic's engine lanes say a view may show | 11 defs: `MechanicView`, `CapabilityView`, ... `arming_stacking` | 230 |
| `src/calculator/survival/receipt_ledger.py` | `src/calculator/survival/receipt_state.py` | the receipt ledger a walk writes its outcomes into | `ReceiptLedger` | 170 |
| `src/calculator/survival/defense_contracts.py` | `src/calculator/survival/receipt_state.py` | the one place `interaction_effects`' four resolvers are read into a state | `_resolved_defence_contracts` | 60 |
| `src/calculator/shield_absorption.py` | `src/calculator/shield_ledger.py` | what a damage instance does to a pool: Lifeline arming, typed then general consumption, health damage, overkill | 8 defs: `_apply_to_health`, `absorb`, ... `_write_pool` | 270 |
| `src/calculator/survival/phases.py` | `src/calculator/survival/actions.py` | when a transition resolves, and what the public timeline calls that phase | 7 defs: `TransitionRank`, `_ORDERING_SLOTS`, ... `support_transition_rank` | 150 |
| `src/calculator/survival/classify.py` | `src/calculator/survival/actions.py` | what an event is: its `ActionKind`, its damage and attack class, and the modifier classes it declares | 19 defs: `ActionKind`, `_DAMAGE_KINDS`, ... `classify_event_kind` | 320 |
| `src/calculator/survival/event_slots.py` | `src/calculator/survival/actions.py` | the kernel's four event references as integers | `NO_SLOT`, `EventSlots`, `EVENT_SLOTS` | 80 |
| `src/calculator/survival/action_key.py` | `src/calculator/survival/actions.py` | the total order the walk consumes actions in, and the fast constructor that stamps it | 34 defs: `event_sequence`, `event_timestamp`, `participant_order`, `_ACTION_DEFAULT_ROW`, 28 `_I_*` index constants, `compiled_damage_action`, `action_key` | 200 |

## Stage 5, 6 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/timed_stacks.py` | `src/calculator/state_lifecycle.py` | the timed stack state a stack rule drives | `_StackEntry`, `TimedStackState` | 495 |
| `src/calculator/window_gates.py` | `src/calculator/state_lifecycle.py` | the window stack gate, Eclipse's two-hit pair and its per-target cooldown | `WindowGateRule`, `WindowProc`, `WindowStackGate` | 210 |
| `src/calculator/cooldowns.py` | `src/calculator/state_lifecycle.py` | cooldowns, global and per-target, and the per-cast-instance cadence | `CooldownRule`, `CooldownState`, `TriggerGate`, `InstanceCadence` | 220 |
| `src/calculator/manaflow_ledger.py` | `src/calculator/resource_ledger.py` | Manaflow: one named passive, two trigger streams, one charge pool | `TRIGGER_ABILITY_CAST`, `TRIGGER_BASIC_ATTACK`, `MANAFLOW_TRIGGERS`, `ManaflowDeclaration`, `ManaflowLedger` | 280 |
| `src/calculator/mana_item_schedules.py` | `src/calculator/resource_ledger.py` | the two sourced item schedules built on the account's receipts, Lost Chapter's Enlighten and Catalyst's Eternity | `EnlightenDeclaration`, `enlighten_schedule`, `CatalystHealRow`, `catalyst_eternity_heal_schedule` | 200 |
| `src/calculator/projectile_defense.py` | `src/calculator/interaction_effects.py` | one champion-to-champion interaction with its own eligibility, composition and public shape | `ProjectileDefense`, `resolve_projectile_defense`, `defense_eligibility`, `defense_composition`, `public_defense` | 235 |

## Stage 6, 7 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/interpreters/damage_deferral.py` | `src/calculator/interpreters/damage_routing.py` | the post-mitigation damage a deferral stores and repays as ticks | 9 defs: `IGNORE_PAIN_NOTE`, `_DEFERRAL_SCHEDULE`, ... `walk_deferral` | 130 |
| `src/calculator/interpreters/swing_schedule.py` | `src/calculator/interpreters/charged_strike.py` | when a rearmed swing lands inside the fight window | `SwingSchedule`, `_merged_schedule`, `_SWING_EPSILON`, `swing_times` | 155 |
| `src/calculator/interpreters/amp_magnitude.py` | `src/calculator/interpreters/delta_amp.py` | how a declared amp magnitude becomes a fraction, and the fields it compiles to | 16 defs: `AMP_FRACTION_FIELD`, `DeltaAmpInterpretationError`, ... `_declared_field` | 240 |
| `src/calculator/interpreters/part_amp.py` | `src/calculator/interpreters/delta_amp.py` | the amps that multiply one damage part rather than a chain slot | 12 defs: `PartAmp`, `EVERY_DAMAGE_CLASS`, ... `resolve_static_holder_amps` | 294 |
| `src/calculator/interpreters/ledger_certification.py` | `src/calculator/interpreters/__init__.py` | which of an owner's declarations put health back into its own survival ledger, and the sentence each publishes | 7 defs: `SurvivalLedgerContribution`, `_LEDGER_CONTRIBUTION_NOTES`, ... `survival_ledger_certifications` | 117 |
| `src/calculator/interpreters/lane_receipts.py` | `src/calculator/interpreters/__init__.py` | the dated receipt for every family and lane pair no interpreter serves | 12 defs: `UnservedLane`, `_PACKET_FED`, ... `_validate_unserved_routes` | 290 |
| `src/calculator/interpreters/compilability.py` | `src/calculator/interpreters/__init__.py` | whether an owner's declarations are all compilable in a scope, and what refuses when they are not | `compilability_for`, `_threshold_regeneration_thresholds`, `uncompilable_item_receipt`, `ReachabilityReport`, `reachability_report` | 139 |

## Stage 7, 7 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/defense_eligibility.py` | `src/calculator/delivery_eligibility.py` | which defense accepts which delivery class, and the window it accepts it in | `DefenseWindow`, `_attacker_name`, `SourceSelection`, `DeliveryAcceptance`, `DefenseEligibility`, `EligibilityDecision` | 285 |
| `src/calculator/defense_composition.py` | `src/calculator/delivery_eligibility.py` | what happens to an event a defense accepted | `UseBudget`, `FullBlockRule`, `DestructionRule`, `ReductionRule`, `DefenseComposition`, `initial_full_block_uses` | 190 |
| `src/calculator/spell_shield_eligibility.py` | `src/calculator/delivery_eligibility.py` | which cast a spell shield blocks, and what the block does | 17 defs: five `SPELL_SHIELD_*_RULE` constants, `SpellShieldRuleDeclaration`, ... `spell_shield_block_decision` | 394 |
| `src/calculator/spell_shield_rearm.py` | `src/calculator/delivery_eligibility.py` | the spell shield's re-arm clock | `SpellShieldRearmClock` | 96 |
| `src/calculator/cleanse_declarations.py` | `src/calculator/cleanse_eligibility.py` | the sourced item cleanse tooltips, one declaration per item | 15 defs: `CleanseActivation`, `CLEANSE_ACTIVE_SOURCES`, ... `item_declaration` | 280 |
| `src/calculator/champion_cleanses.py` | `src/calculator/cleanse_eligibility.py` | the sourced champion abilities that remove control | `CHAMPION_CLEANSE_SOURCES`, `RENGAR_EMPOWERED_W_CLEANSE_DECLARATION`, `CHAMPION_CLEANSE_DECLARATIONS` | 400 |
| `src/calculator/control_intervals.py` | `src/calculator/cleanse_eligibility.py` | span algebra over control and downtime intervals | 7 defs: `_interval_bounds`, `_interval_kind`, ... `truncate_intervals` | 165 |

## Stage 8, 13 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/champions/renata_bailout_authority.py` | `src/calculator/champions/renata_glasc.py` | the field-by-field source adjudication that keeps Bailout's lethal half withheld | `BAILOUT_AUTHORITY` | 262 |
| `src/calculator/champions/aurelion_sol_stardust.py` | `src/calculator/champions/aurelion_sol.py` | the Stardust stack pool, and what a Q burst and an E execute are worth per stack | 9 defs: `_StardustRule`, `AURELION_SOL_STARDUST_RULE`, ... `_Q_BURSTS_PER_CHANNEL` | 135 |
| `src/calculator/champions/aphelios_weapons.py` | `src/calculator/champions/aphelios.py` | which of the five weapons is in hand, what each adds on hit, and the Weapon Master points | 13 defs: `_WEAPON_INDEX`, `_WEAPON_LABELS`, ... `_weapon_master` | 183 |
| `src/calculator/champions/module_survey.py` | `src/calculator/champions/module_contract.py` | reads each contract fact off a module's three declaration sites and refuses a malformed one | 12 defs: `_present`, `_stat_conversion`, ... `contract_from_module` | 475 |
| `src/calculator/champions/packet_parsers.py` | `src/calculator/champions/packet_module.py` | a packet row becomes a slot parser | 12 defs: `_packet_specs`, `_ranked`, ... `_compiled_slot` | 455 |
| `src/calculator/champions/entry_shape.py` | `src/calculator/champions/engine.py` | every key an emitted entry may carry, and the refusal for one it may not | 9 defs: `_ALLOWED_ENTRY_KEYS`, `_ALLOWED_DEBUFF_KEYS`, ... `_SHARED_INSTANT` | 350 |
| `src/calculator/champions/slot_cc.py` | `src/calculator/champions/engine.py` | the module's crowd-control declaration, stamped onto the parts a slot emits | 7 defs: `CC_PER_PART`, `_apply_module_cc`, ... `_empower_marker_part` | 260 |
| `src/calculator/champions/registry.py` | `src/calculator/champions/__init__.py` | the validated contract for a name, and every fact read off it | 21 defs: `_MODULE_CONTRACTS`, `module_basename`, ... `declared_options_rows` | 250 |
| `src/calculator/champions/option_rotation.py` | `src/calculator/champions/__init__.py` | what each declared `OPTIONS` key means to the rotation resolver | `_ROTATION_CLASSIFICATIONS`, `_ROTATION_ROLES`, `get_champion_option_rotation` | 440 |
| `src/calculator/champions/slot_extract.py` | `src/calculator/champions/slotlib.py` | the one `effects[].leveling[].modifiers[]` walk | 20 defs: `ModifierOverride`, `PER_LEVEL_SCALING`, ... `build_stats_context` | 350 |
| `src/calculator/champions/slot_entries.py` | `src/calculator/champions/slotlib.py` | the entry dicts a slot parser hands the fight engine | 11 defs: `MODULE_FORMULA_ZERO`, `STEROID_ZERO`, ... `ability_on_hit_entry` | 420 |
| `src/calculator/champions/slot_control.py` | `src/calculator/champions/slotlib.py` | a control atom, and the archetypes that attach one to a slot | 13 defs: `_resolve_source`, `_control_duration_atom`, ... `with_control_event` | 420 |
| `src/calculator/champions/stack_mechanics.py` | `src/calculator/champions/darius.py`, `src/calculator/champions/briar.py` | a stacking damage-over-time a champion's basic attacks apply, and the buff a stack count arms | the shared `stacking_dot` payload behind `_hemorrhage` and `_crimson_curse` | not estimated |

## Stage 9, 24 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/rune_effect_types.py` | `src/calculator/rune_effects.py` | the effect a rune compiler produces | 18 defs: `RuneTrigger`, `_always_armed`, ... `RuneEffect` | 445 |
| `src/calculator/rune_options.py` | `src/calculator/rune_effects.py` | the request inputs a rune's formula declares | `RuneOptionKind`, `RuneOption`, `_option_value`, `armed_by_option`, `stack_count_option` | 145 |
| `src/calculator/keystone_effects.py` | `src/calculator/rune_effects.py` | the effect type each keystone compiles to | 11 defs: `KeystoneAeryEffect`, `KeystoneGuardianEffect`, ... `KeystoneDarkHarvestEffect` | 458 |
| `src/calculator/keystone_deathfire.py` | `src/calculator/rune_effects.py` | Deathfire Touch, the one keystone whose effect carries its own tick schedule | `KeystoneDeathfireEffect` | 47 |
| `src/calculator/rune_values.py` | `src/calculator/rune_effects.py` | the typed, fail-loud read of one cached rune record | 22 defs: `RuneValues`, `_FULL_LEVEL_COUNT`, ... `no_damage_compiler` | 310 |
| `src/calculator/rune_page.py` | `src/calculator/rune_effects.py` | the page's own shape rule: one keystone, five runes, three shards | 18 defs: `SECONDARY_PATH_MINORS`, `KEYSTONE_ROW`, ... `resolve_rune_page` | 320 |
| `src/calculator/rune_stat_grants.py` | `src/calculator/rune_effects.py` | the stat grants a compiled page resolves, and the door `stats.py` reads them through | 7 defs: `adaptive_force_attack_damage_ratio`, `adaptive_force_split`, ... `compile_rune_page` | 150 |
| `src/calculator/rune_patterns.py` | `src/calculator/rune_parser.py` | every regex and rule tuple the rune parser matches against | about 90 defs: `_PARAM_LINE`, `_PP_TEMPLATE`, ... `_RD_FLAT_RULES` | 465 |
| `src/calculator/pp_template.py` | `src/calculator/rune_parser.py` | the Wiki `{{pp}}` progression template evaluator | 13 defs: `_ALLOWED_PP_NODES`, `parse_rune_template`, ... `_recurring_decimal` | 300 |
| `src/calculator/rune_leveling.py` | `src/calculator/rune_parser.py` | a rune's per-rank rows, split rows and per-stack grants | 7 defs: `_parse_leveling`, `_record_key_span`, ... `_parse_ultimate_haste_stacks` | 230 |
| `src/calculator/rune_prose.py` | `src/calculator/rune_parser.py` | the numbers a rune states in a sentence instead of a row | `_parse_prose_rules`, `_parse_conditional_amp` | 205 |
| `src/calculator/rune_payload.py` | `src/calculator/rune_parser.py` | the cached rune record `data_updater` writes | 20 defs: `DEFAULT_LEVEL_COUNT`, `_IMPLICIT_LEVEL_RANGES`, ... `RESERVED_CACHE_KEYS` | 215 |
| `src/calculator/wiki_templates.py` | `src/calculator/passive_parser.py` | the Wiki template reader every item parser shares: template splitting, safe expression evaluation, value extraction, field specs | about 43 defs: `_find_template_end`, `_split_template_args`, ... `_get_cooldown_field` | 390 |
| `src/calculator/parse_on_hit.py` | `src/calculator/passive_parser.py` | the on-hit, spellblade and burn item parsers | 18 defs: `_parse_simple_on_hit`, `_parse_current_hp_on_hit`, ... `_parse_thorns` | 395 |
| `src/calculator/parse_procs.py` | `src/calculator/passive_parser.py` | the triggered and active item parsers | 19 defs: `_parse_bullseye`, `_parse_stormsurge_trigger`, ... `_parse_harmony` | 355 |
| `src/calculator/parse_amplifiers.py` | `src/calculator/passive_parser.py` | the damage-amplifier item parsers | 16 defs: `_parse_zeke_frostfire`, `_parse_blackfire_amp`, ... `_parse_overlord_retribution` | 295 |
| `src/calculator/parse_stat_conversions.py` | `src/calculator/passive_parser.py` | the stat-conversion and defensive item parsers | 25 defs: the two `_parse_mana_to_*_awe`, `_parse_rabadons_opus`, ... `_parse_shadowflame` | 285 |
| `src/calculator/parse_on_hit_specials.py` | `src/calculator/passive_parser.py` | the named on-hit item parsers with their own shapes | 11 defs: `_parse_dead_mans_plate`, `_parse_heartsteel`, ... `_parse_yun_tal_crit_stacks` | 275 |
| `src/calculator/item_coverage_status.py` | `src/calculator/item_coverage.py` | the coverage answer: statuses, lanes, and `ItemCoverage` | 11 defs: `ItemCoverageStatus`, `_REFUSAL_STATUSES`, ... `NO_RUNTIME_BEHAVIOR` | 215 |
| `src/calculator/stats_only_items.py` | `src/calculator/item_coverage.py` | the certified stats-only effect text and its fingerprint | `_STATS_ONLY_CERTIFIED_EFFECT_TEXT`, `stats_only_effect_fingerprint` | 480 |
| `src/calculator/target_coverage.py` | `src/calculator/item_coverage.py` | what a target build must be for the timeline to price it, and what the optimizer may hold | 18 defs: `_DURABILITY_PACKET_KINDS`, `_HOLDER_SURVIVAL_FIELDS`, ... `require_calculation_item_coverage` | 355 |
| `src/calculator/attacker_claim_evidence.py` | `src/calculator/item_coverage.py` | the authored evidence behind an attacker-lane claim | `_ISSUE_REF_ONLY_ITEMS`, `_SOURCE_REFS`, `_ATTACKER_STATE_HOMES` | 290 |
| `src/calculator/target_claim_evidence.py` | `src/calculator/item_coverage.py` | the authored evidence behind a target-lane claim | `_TARGET_MODELED_IMPLS`, `_TARGET_CERTIFIED_IMPLS`, `_UTILITY_HOMES`, `_SUPPORT_PACKET_CLAIMS` | 280 |
| `src/calculator/coverage_claims.py` | `src/calculator/item_coverage.py` | the loop that turns authored evidence into `Claim` records | 19 defs: `_DUAL_SIDED_MECHANICS`, `_CLAIM_LANE_SOURCES`, ... `FRONTIER` | 420 |

## Stage 10, 2 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/quantity.py` | `src/calculator/ability_spec.py` | what a published number is: measured, a structural zero, withheld, or starved | 10 defs: `WithheldHasNoValue`, `StarvedSignal`, ... `Quantity` | 215 |
| `src/calculator/control_spec.py` | `src/calculator/ability_spec.py` | the one crowd-control vocabulary, its three partitions, and the control event a cast carries | 10 defs: `IMMOBILIZING_CC_KINDS`, `NON_IMMOBILIZING_CC_KINDS`, ... `ControlEvent` | 165 |

## Stage 11, 29 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/item_sustain_events.py` | `src/calculator/pipeline.py` | the healing an item did, read back off a finished fight result | `_item_self_healing_events`, `_timestamped_damage_events` | 425 |
| `src/calculator/rune_sustain_events.py` | `src/calculator/pipeline.py` | the healing a rune page did, read back the same way | `_rune_heal_times`, `_rune_self_healing_events`, `_keystone_self_healing_events`, `_saturated_omnivamp_percent` | 175 |
| `src/calculator/fight_request_bounds.py` | `src/calculator/pipeline.py` | what a public fight request may say, and the readers that coerce it | 20 defs: `DEFAULT_TARGET`, `DEFAULT_FIGHT_DURATION`, ... `_request_target_durability` | 230 |
| `src/calculator/fight_receipts.py` | `src/calculator/pipeline.py` | the receipts and display splits attached to a finished fight | `_attach_engine_receipts`, `_attach_display_splits`, `_annotate_deathfire_categories` | 145 |
| `src/calculator/champion_loadout.py` | `src/calculator/scenario.py` | one roster card: its champion, level, boots, items, item state, role and quest state, and what resolving it produces | 9 defs: `MAX_LOADOUT_ITEMS`, `_validate_champion_options`, ... `resolve_named_item` | 420 |
| `src/calculator/ally_packet_shape.py` | `src/calculator/item_support_effects.py` | what one cross-participant item packet is, and the producer it came from | 11 defs: `_DAMAGE_MODIFIER_KIND`, `_MISSING`, ... `_packet` | 225 |
| `src/calculator/ally_packet_recipient.py` | `src/calculator/item_support_effects.py` | re-pricing a one-ally packet for the ally actually selected | 8 defs: `_CHAIN_KINDS`, `_CHAIN_FRACTION_KEYS`, ... `repriced_for_recipient` | 100 |
| `src/calculator/support_event_view.py` | `src/calculator/item_support_effects.py` | the fight-result streams a support packet is priced from, and the refusal when the view is starved | 14 defs: `_support_triggers`, `_cc_event_stream`, ... `_bus_streams` | 305 |
| `src/calculator/item_support_quests.py` | `src/calculator/item_support_effects.py` | the non-combat branches: gold, progression, wards and vision | the I6 and I7 branches of `derive_item_support_effects`, each a new `_x_packets(ctx)` | 230 |
| `src/calculator/item_support_everlasting.py` | `src/calculator/item_support_effects.py` | Fimbulwinter's Everlasting: the arming rule and every named denial | the I8 branch of `derive_item_support_effects` | 275 |
| `src/calculator/item_support_shred.py` | `src/calculator/item_support_effects.py` | shared target modifiers a holder puts on an enemy | the I9 and I10 branches of `derive_item_support_effects` | 215 |
| `src/calculator/item_support_enchanter.py` | `src/calculator/item_support_effects.py` | the enchanter passives an authored ally trigger arms | the I11 branches of `derive_item_support_effects` | 300 |
| `src/calculator/item_support_actives.py` | `src/calculator/item_support_effects.py` | the ally actives priced at the cast | 4 defs: `_support_quest_packets`, `_cleanse_active_packet`, `_cleanse_movement_entry`, `_self_cleanse_items`, plus the I12 branches | 370 |
| `src/calculator/support_scan.py` | `src/calculator/support_effects.py` | which champion slots the cached rows say heal or shield an ally, and the profile that answer folds into | 25 defs: `_ability`, `_first_attribute`, ... `_support_profile` | 370 |
| `src/calculator/support_row_metadata.py` | `src/calculator/support_effects.py` | what one support row publishes: recipient scaling, rank, duration and timing | 11 defs: `_SHIELD_DURATION_ATOM_QUERIES`, `_INVULNERABILITY_ATOM_QUERIES`, ... `_invulnerability_timing_metadata` | 385 |
| `src/calculator/support_bailout.py` | `src/calculator/support_effects.py` | Renata Glasc's Bailout: its ramp, its denial rows and the shape it withholds | 20 defs: fourteen `_BAILOUT_*` constants, `_bailout_authority`, ... `_bailout_denial_rows` | 275 |
| `src/calculator/support_champion_packets.py` | `src/calculator/support_effects.py` | the sourced per-champion metadata and follow-up packets an ally receives | 9 defs: `_morgana_black_shield_metadata`, `_target_max_health_shield_metadata`, ... `_yuumi_conversion_shield_packet` | 350 |
| `src/calculator/optimizer_candidates.py` | `src/calculator/optimizer.py` | which items a search may legally hold, and what they cost | 11 defs: `_ordinary_sr_items`, `get_eligible_legendaries`, ... `get_purchase_items` | 120 |
| `src/calculator/build_evaluation.py` | `src/calculator/optimizer.py` | scoring one candidate build through the same `run_fight` the manual path uses | `_evaluate_build`, `_evaluate_build_uncached`, `_build_timeline_coverage`, `_build_receipt_key` | 425 |
| `src/calculator/build_receipts.py` | `src/calculator/optimizer.py` | what an evaluated build publishes | `_public_build_receipt`, `_public_search_timeline_coverage` | 95 |
| `src/calculator/build_search.py` | `src/calculator/optimizer.py` | greedy fill and hill climbing over legendary slots | `_greedy_fill`, `_score_with_swap`, `_hill_climb` | 220 |
| `src/calculator/purchase_plans.py` | `src/calculator/optimizer.py` | the gold-constrained plan space: enumeration, pricing and the two chain builders | `_PurchaseSearch`, `_enumerate_affordable_shapes`, `_greedy_purchase_chain`, `_improve_purchase_chain` | 480 |
| `src/calculator/purchase_search.py` | `src/calculator/optimizer.py` | `optimize_purchase`, the one gold-budget search the API calls | `optimize_purchase`, `_score_exhaustive_purchase_plans`, `_run_purchase_local_search` | 430 |
| `src/calculator/bis_candidates.py` | `src/calculator/bis.py` | which items a BIS search ranks, for which subject, in which order | `bis_main_request`, `bis_replaced_loadout`, `role_scoped_bis_candidates`, `bis_candidate_pool`, `roster_target_coverage`, `enemy_bis_rank_key` | 180 |
| `src/calculator/bis_objective.py` | `src/calculator/bis.py` | what BIS optimises for, and how one candidate folds into that number | 12 defs: `BIS_OBJECTIVES`, `BIS_UNMODELED_DEFENSIVE_EFFECTS`, ... `_bis_dispositions` | 420 |
| `src/calculator/cast_order_overrides.py` | `src/calculator/rotation_resolver.py` | the champions whose cast order is asserted by hand, and the reason each one is | `_DEFAULT_RATIONALE`, `ComboRule`, `ORDER_OVERRIDE_REASONS`, `CAST_ORDER_OVERRIDES`, `_validate_override_reasons` | 290 |
| `src/calculator/cast_edge_markers.py` | `src/calculator/rotation_resolver.py` | the parsed-text markers and slot corpus an inferred edge is read out of | about 36 defs: `_DIRECT_EDGE_KIND`, `_DAMAGE_AMP_STAT_KEYS`, six `_ATTR_*` and twelve `_P_*` patterns, ... `_cc_orders_the_burst` | 260 |
| `src/calculator/cast_edge_inference.py` | `src/calculator/rotation_resolver.py` | the twelve edge kinds inferred from a champion's own rows | `detect_setup_consume_edges` | 480 |
| `src/calculator/champion_rotation_rule.py` | `src/calculator/rotation_resolver.py` | the per-champion DPS matrix and the `ComboRule` fitted to one fight from it | 9 defs: `_MATRIX_SPECS`, `_MATRIX_DPS_CACHE`, ... `derive_champion_rule` | 470 |

## Stage 12, 31 modules

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `scripts/golden_leaf_diff.py` | `scripts/golden_snapshot.py` | what a golden diff is, and how one is triaged | 32 defs: `PAIR_SNAPSHOT_KIND`, `COUPLED_SNAPSHOT_KIND`, ... `receipt_numeric_leaves` | 370 |
| `scripts/golden_coverage_arms.py` | `scripts/golden_snapshot.py` | which declaration no committed scenario arms | 24 defs: `bench_roster_scenarios`, `_uncovered_producers`, ... `_refuse_unarmed_swing_terms` | 345 |
| `scripts/golden_coupled_scenarios.py` | `scripts/golden_snapshot.py` | the coupled golden's acceptance matrix, one roster scenario per row | 4 defs: `CoupledScenario`, the `SYNDRA_PIN_*` constants, `_syndra_pin_scenarios`, `COUPLED_SCENARIOS` | 400 |
| `scripts/golden_requests.py` | `scripts/golden_snapshot.py` | the two request builders a coupled scenario is spelled with | `_syndra_pin_request`, `_roster_request` | 100 |
| `scripts/golden_pair_capture.py` | `scripts/golden_snapshot.py` | capturing the pair engine's numbers, one sweep per scenario family | 5 defs: `snapshot_champion_baselines`, `snapshot_registered_fights`, ... `build_snapshot`, plus the scenario constants | 450 |
| `scripts/frontier_scan.py` | `scripts/behavior_frontier.py` | the classification vocabulary and the scan that indexes every site from `src/` | 19 defs: `ROOT`, `LEDGER_SCOPE`, ... `_undeclared_base_blocker` | 480 |
| `scripts/frontier_deferrals.py` | `scripts/behavior_frontier.py` | the campaign stages, the creditor of each deferral, and what is owed | 22 defs: the `COUNTER_4_*` constants, `CAMPAIGN_STAGES`, ... `_overdue_failures` | 390 |
| `scripts/frontier_targets.py` | `scripts/behavior_frontier.py` | the targets each counter must meet, and the no-runtime-behavior ceiling | `TARGET_CRITERIA`, `target_block`, `_target_failures`, `NO_RUNTIME_BEHAVIOR_CEILING`, `no_runtime_behavior_block` | 140 |
| `scripts/frontier_zero_policy.py` | `scripts/behavior_frontier.py` | the zero-policy frontier over the champion modules | 13 defs: `CHAMPIONS_ROOT`, `ZERO_POLICY_ISSUE`, ... `_zero_policy_failures` | 255 |
| `tests/test_frontier_counters.py` | `tests/test_behavior_frontier.py` | the counter one to three gate | the 33-330 band | 300 |
| `tests/test_frontier_zero_policy.py` | `tests/test_behavior_frontier.py` | the zero-policy frontier gate | the 338-670 band | 335 |
| `tests/test_frontier_deferrals.py` | `tests/test_behavior_frontier.py` | counter four's deferrals and routes | the 677-876 band | 200 |
| `tests/test_frontier_targets.py` | `tests/test_behavior_frontier.py` | the targets and stages gate | the 879-1249 band | 390 |
| `scripts/ability_row_compare.py` | `scripts/patch_regression.py` | does a cached ability row still match the game's spell record | `_numeric_values`, ... `_compare_entry_rows`, `_wiki_row_count` | 345 |
| `scripts/game_file_access.py` | `scripts/patch_regression.py` | fetching and verifying the client's shipped data | `_download`, `download_game_files`, `verify_wads`, `extract_champion_bin_via_cdtb`, the CDTB constants | 180 |
| `scripts/patch_staleness.py` | `scripts/patch_regression.py` | how stale each cached table is against the live patch | `build_staleness` plus its constants and the stat maps | 110 |
| `scripts/authority_files.py` | `scripts/patch_mechanics.py` | which files a patch may only be pulled into when clean, and how each is verified | 8 defs: `AUTHORITY_FILES`, `_sha256_bytes`, ... `_download_bytes` | 130 |
| `scripts/full_entry_items.py` | `scripts/full_entry_audit.py` | what effects an item's cached entry is expected to declare, and which the runtime models | 6 defs: `audit_item_names`, `_cached_record`, ... `_item_effect_coverage` | 250 |
| `scripts/wiki_query.py` | `scripts/full_entry_audit.py` | the query seam every audit reads the Wiki through | 8 defs: `InfrastructureError`, `resolve_query_tool`, ... `_template_receipt` | 110 |
| `scripts/cast_marker_derivation.py` | `scripts/cast_dependency_audit.py` | the AST derivation of a slot's markers and option states | 11 defs: `apply_marker_keys`, `_apply_atom_loop`, ... `slot_option_keys` | 250 |
| `scripts/cast_audit_ledgers.py` | `scripts/cast_dependency_audit.py` | the audit's ledgers and the failures they raise | `_activation_ledger`, ... `_override_frontier` | 360 |
| `scripts/bench_scenarios.py` | `scripts/bench_coupled_optimizer.py` | the fixed rosters and builds every coupled bench and golden coverage arm is measured on | `CASSIOPEIA_SCENARIO`, `FIVE_CHAMPION_SCENARIO`, `MUNDO_SCENARIO`, `SYNDRA_MANDATE_SCENARIO`, `SCENARIOS`, `PROBE_BUILDS` | 145 |
| `scripts/work_counters.py` | `scripts/bench_coupled_optimizer.py` | what one coupled evaluation costs, counted | `WorkCounters`, `residual`, `allocation_probe`, `attach_allocation_peaks` | 120 |
| `scripts/wiki_packet_specs.py` | `scripts/build_reviewed_modules.py` | a cached wiki ability row becomes a packet spec | `_damage_kind`, `_wiki_cooldown`, `_wiki_packet`, `_wiki_specs`, `_axword_spec` | 285 |
| `scripts/census_cells.py` | `scripts/coverage_census.py` | the cell producers the census sweep folds | 9 defs: `CensusSweep`, `_mode_cells`, ... `_global_cells` | 155 |
| `tests/resolver_context.py` | `tests/coverage_resolver.py` | the session seam and node facts both resolver halves read through | 12 defs: `EvidenceUnresolved`, `ResolverContext`, ... `full_session` | 250 |
| `tests/node_evidence.py` | `tests/coverage_resolver.py` | whether a `TestRef` resolves against the collected nodes | 21 defs: `split_node_id`, `_mark_name`, ... `resolve_test_ref` | 450 |
| `tests/packet_evidence.py` | `tests/coverage_resolver.py` | a `_packet` source string and where it was built | 7 defs: `PacketSite`, `render_source_argument`, ... `_builder_modules` | 180 |
| `tests/paired_authority.py` | `tests/coverage_resolver.py` | a mechanic with two declared halves | `_DUAL_SIDED_AUTHORITIES`, `resolve_paired_sides`, `_capabilities`, `_resolve_pair_half`, `_resolve_owner_policy` | 130 |
| `tests/symbol_evidence.py` | `tests/coverage_resolver.py` | evidence that names a thing in the tree, resolved to it | 24 defs: `PACKAGE`, `PACKAGE_ROOT`, ... `resolve_absence` | 420 |
| `tests/front_door.py` | `tests/coverage_resolver.py` | which modules a test module imports by dotted path | `MissingFrontDoor`, `imported_package_modules`, `front_door_report` | 90 |

## Stage 13, 67 modules

Every module comes out of `src/calculator/damage.py`. The `from` column gives the owning map's
section id: `A1` to `A21` for map A, `S1` to `S14` for map B, `C1` to `C17` for map C, and `D-A`
to `D-P` for map D. The plan sets `resists`, `event_rows`, `mana_walk`, `ability_rotation`,
`auto_simulation`, `on_hit_layering` and `single_proc_on_hits` over the maps' `fight_resists`,
`event_row`, `fight_mana_walk`, `fight_rotation`, `fight_auto_simulation` and `fight_on_hit`.
Map A calls the ordered ledger `damage_ledger.py` and map D calls it `event_ledger.py`. This
roster takes map D's name, to match the plan's `event_rows`.

| new module | from | what the name means | defs that move | lines |
|---|---|---|---|---|
| `src/calculator/cast_control_marker.py` | `D-L` | the crowd-control marker a declared entry carries, read by the ordered ledger | `_declared_cc_kind`, `_entry_control_scope`, `_declared_cc_marker` | 39 |
| `src/calculator/fight_results.py` | `A16`, `S10c`, `S12`, `S14` | the typed values the fight's steps hand each other | `AutoAttackResult`, `OnHitResult`, `SpellbladeResult`, `RotationResult` | 110 |
| `src/calculator/fight_config.py` | `A1`, `A3` | what one fight is configured to be, including the specs a user's option selections resolve through | 9 defs: `BASE_CRIT_MULTIPLIER`, `_declared_options`, ... `FightConfig` | 285 |
| `src/calculator/fight_state.py` | `A4`, `D-E` | the mutable record every step function is threaded through | `FightState`, `_damage_inputs`, `_held_owners`, `_crit_profile` | 215 |
| `src/calculator/resists.py` | `A2` | the target's resistances and this attacker's penetration resolved together, and the two functions that spend them | `Resists`, `_mitigate`, `_apply_physical_damage_reduction` | 265 |
| `src/calculator/event_rows.py` | `A9` | one row of the reconstructed ledger, and the receipt readers that shape it | 13 defs: `_row_time`, `_damage_type_fields`, ... `_CAST_TIME_RESOLUTION`, plus `_finite_numeric_receipt` | 195 |
| `src/calculator/event_ledger.py` | `A10` | the engine's certified damage order, reconstructed from its own rows | `_ordered_damage_events` | 345 |
| `src/calculator/cast_slots.py` | `A14`, `A16` | the cast-slot vocabulary and the records the rotation hands on | `_base_slot`, `_slot_is_cast`, `AbilityItemApplication`, `RotationResult` | 90 |
| `src/calculator/empower_declaration.py` | `A17` | what an `empowers_next_auto` payload declares, and where its swings landed | 6 defs: `_empower_hits`, `_empower_cooldown_delay`, ... `BurstSwingSchedule` | 95 |
| `src/calculator/fight_mitigation.py` | `A5` | what the target's own defenses do to an instance that already met resistance | 6 defs: `_apply_basic_amp`, `_apply_target_basic_damage_reduction`, ... `_mitigate_hits` | 160 |
| `src/calculator/target_debuffs.py` | `A18` | a `target_debuff`'s uptime, its resistance reduction, and the two shapes that gate it | 6 defs: `_ability_mr`, `_debuff_coverage`, ... `_make_shred_ramp` | 200 |
| `src/calculator/on_hit_stream.py` | `A6`, `A7` | what a swing pays back, and what schedules an on-hit application | 7 defs: `_active_lifesteal_amount`, `_add_lifesteal_events`, ... `_schedule_cooldown_procs` | 355 |
| `src/calculator/decaying_health_walk.py` | `A8` | pricing a proc formula that reads current health against a target that is losing it | 8 defs: `StackingProc`, `OnHitProc`, ... `_simulate_current_health_on_hit` | 340 |
| `src/calculator/ledger_coverage.py` | `A11` | which rows the engine calls certified, and why the rest are coarse | `_event_timeline_coverage`, `_control_armed_holder_shields`, `_control_armed_event_coverage` | 235 |
| `src/calculator/pool_walk.py` | `A12` | the target's live pools, walked event by event | `_ThresholdHealDrip`, `_LIANDRY_BURN_KEY`, `_liandry_max_health_reprice`, `_simulate_ordered_damage` | 255 |
| `src/calculator/cast_parts.py` | `A19` | pricing an ability's typed damage parts over its casts | `_evaluate_cast_parts`, `_apply_post_hit_proc`, `CastPricing`, `_NO_PRICING` | 375 |
| `src/calculator/cast_schedule.py` | `A20` | when each ability casts, and the plan that lands in | 13 defs: `_navori_effective_cd`, `_immobilize_ability_haste`, ... `_resolve_cast_plan` | 460 |
| `src/calculator/resource_admission.py` | `A21`, `S2`, `S4` | which resource walk admits this fight's casts, and the skeleton both walks share | `_apply_resource_limits`, `_cast_admission_events`, `_resource_timeline`, `_CastAdmission`, plus both account walks | over 500 |
| `src/calculator/stat_buff_ultimates.py` | `A15` | an ability's stat grant, and everything re-resolved from a buffed stat | `_apply_stat_buff_ultimates` | 245 |
| `src/calculator/combat_state.py` | `A13` | fight setup: resolve resistances, amps and attack timing into a `FightState` | 6 defs: `_shred_slot`, `_part_amp`, ... `_resolve_combat_state` | 430 |
| `src/calculator/fight_shaped_charge.py` | `S9` | ability-triggered lethality procs | `_strike_declaration`, `_next_authored_event`, `_shaped_charge_proc_receipts`, `_add_shaped_charge_damage` | 185 |
| `src/calculator/fight_dot_ticks.py` | `S8` | splitting a damage-over-time total into sourced ticks | 6 defs: `_ability_dot_tick_events`, `_author_ability_dot_events`, ... `_periodic_damage_events` | 355 |
| `src/calculator/fight_precomputed_procs.py` | `S7` | ability damage that fires a fixed number of times | `_add_precomputed_proc_damage` | 360 |
| `src/calculator/fight_stack_timeline.py` | `S5` | when a stacking damage-over-time stack lands, and everything that gates | 7 defs: `StackApplication`, `CastPricing`, ... `_build_stack_timeline` | 285 |
| `src/calculator/fight_empower_windows.py` | `S12` | a passive a cast arms and a later action spends | 7 defs: `OnHitResult`, `_on_hit_declaration`, ... `_declared_slot_stacks` | 280 |
| `src/calculator/fight_swing_schedule.py` | `S10` | when auto attacks land | 13 defs: `_weave_around_bursts`, `_swings_at_rate`, ... `_apply_spellblade_attack_speed` | 455 |
| `src/calculator/fight_spellblade.py` | `S14` | Spellblade arming, proc times, and the priced packet | 6 defs: `SpellbladeResult`, `_spellblade_proc_times`, ... `_add_spellblade_damage` | 455 |
| `src/calculator/fight_cast_plan.py` | `S1` | the admitted cast plan, and the admission skeleton every account walks | 6 defs: `CastPlan`, `_resolve_cast_plan`, ... `_CastAdmission` | 330 |
| `src/calculator/fight_mana_declarations.py` | `S3` | what a build declares about mana before anything is walked | 17 defs: `_manaflow_hit_identity`, `_manaflow_swing_rows`, ... `_mark_refund_decl_for_state` | 485 |
| `src/calculator/fight_energy_walk.py` | `S2` | the one non-mana account: a clamped pool with a temporary maximum | `_apply_energy_resource_limits` | 108 |
| `src/calculator/mana_walk.py` | `S4` | the one walk that owns every mana transition against a single `resource_ledger` account | `_apply_mana_resource_limits`, `_schedule_enlighten`, `_resource_ledger_public` | 750 |
| `src/calculator/ability_rotation.py` | `S6` | resolving the cast schedule, admitting it against resources, then pricing every cast | `_compute_ability_rotation` | 760 |
| `src/calculator/auto_simulation.py` | `S11` | per-swing crit rolls with the seven overlapping riders | `_simulate_auto_attacks` | 600 |
| `src/calculator/on_hit_layering.py` | `S13` | the one on-hit authoring site | `_layer_on_hit_effects` | 745 |
| `src/calculator/damage_burns.py` | `C1` | item damage on a clock: burns, auras, fixed-interval strikes | `_periodic_damage_events`, `_periodic_declaration`, `_declared_periodic_ticks`, `_add_burn_damage` | 259 |
| `src/calculator/item_proc_triggers.py` | `C2` | when a cooldown proc is allowed to fire | `_unique_ledger_hits`, `_ability_damage_proc_triggers`, `_champion_damage_proc_triggers`, `_damage_threshold_trigger_time` | 131 |
| `src/calculator/eclipse_stack_gate.py` | `C3` | Eclipse's two-stacks-in-a-window schedule and its withheld candidates | `_EclipseStackTrigger`, `_stacked_champion_proc_times` | 382 |
| `src/calculator/item_cast_procs.py` | `C4` | the row a cast-triggered item proc publishes | `_proc_declaration`, `_charged_proc_target_share`, `_add_item_proc_damage` | 233 |
| `src/calculator/rune_streams.py` | `C5` | the fight event stream a rune declares it watches | 8 defs: `_rune_instance_times`, `_record_rune_proc_row`, ... `_page_effects` | 130 |
| `src/calculator/rune_page_damage.py` | `C6` | what the compiled rune page prices, and what it discloses when it prices nothing | 7 defs: `_add_rune_proc_damage`, `_RUNE_TRIGGER_SHORTFALLS`, ... `_add_rune_ability_proc_damage` | 152 |
| `src/calculator/keystone_casts.py` | `C7` | Aery and Aftershock: one proc per accepted cast of a declared shape | `_aery_trigger_times`, `_add_keystone_aery_damage`, `_aftershock_trigger_events`, `_add_keystone_aftershock_damage` | 173 |
| `src/calculator/keystone_ledger_walk.py` | `C8` | Dark Harvest and Deathfire: keystones replayed over the ordered event ledger | `_dark_harvest_trigger_event`, `_add_keystone_dark_harvest`, `_deathfire_trigger_events`, `_add_keystone_deathfire` | 328 |
| `src/calculator/keystone_attacks.py` | `C9` | Grasp, Hail of Blades, Lethal Tempo and Fleet: keystones that own or ride the swing schedule | 7 defs: `_grasp_proc_events`, `_add_keystone_grasp_damage`, ... `_add_keystone_fleet_footwork` | 449 |
| `src/calculator/keystone_stacks.py` | `C10` | First Strike, Press the Attack and Conqueror: stacks that become an amplifier | 8 defs: `_certified_only_pool`, `_add_rune_window_amp_damage`, ... `_price_rune_proc_amp` | 439 |
| `src/calculator/stack_ledgers/account.py` | `C11` | one champion stack resource's receipts, in the shape every kind publishes | `StackEvent`, `_stack_receipt_row`, `_StackAccount`, `_resource_ledger` | 107 |
| `src/calculator/stack_ledgers/senna.py` | `C12` | Senna's soul count as a receipt ledger | `_add_senna_souls` | 134 |
| `src/calculator/stack_ledgers/ashe.py` | `C12` | Ashe's Focus stacks and the denial receipt | `_feed_ashe_focus_stack`, `_add_ashe_focus`, `_add_focus_denial` | 265 |
| `src/calculator/stack_ledgers/ksante.py` | `C12` | K'Sante's Path Maker counter | `_add_ksante_path_maker` | 149 |
| `src/calculator/stack_ledgers/heimerdinger.py` | `C12` | Heimerdinger's W and E charge counters | `_add_heimerdinger_w_e` | 145 |
| `src/calculator/stack_ledgers/bard.py` | `C12` | Bard's chime count | `_add_bard_travelers_call` | 234 |
| `src/calculator/stack_ledgers/aurelion_sol.py` | `C12` | Aurelion Sol's Stardust count | `_add_aurelion_sol_stardust` | 159 |
| `src/calculator/stack_ledgers/rengar.py` | `C12` | Rengar's Ferocity timeline | `_build_ferocity_timeline`, `_slot_ordinals`, `_add_rengar_ferocity` | 232 |
| `src/calculator/item_actives.py` | `C13` | active-item damage, skipped when actives are excluded | `_add_item_active_damage` | 118 |
| `src/calculator/muramana.py` | `C15` | Muramana's per-cast packet identity and shock lockout | 7 defs: `_MuramanaCastReceipt`, `_muramana_cast_receipt`, ... `_muramana_proc_events` | 216 |
| `src/calculator/energized_packets.py` | `C16` | packets authored before the event that triggered them | `_first_damaging_ability_event`, `_author_energized_ability_proc`, `_first_auto_damage_by_auto_for_health_walk` | 195 |
| `src/calculator/copied_on_hit.py` | `C17` | one on-hit application copied onto a second subject | 7 defs: `_bolt_declaration`, `_copied_on_hit_declaration`, ... `_add_copied_stacking_on_hit_packets` | 297 |
| `src/calculator/damage_breakdown.py` | `D-P` | splitting a finished fight breakdown by stream and by damage type | `_is_auto_stream_key`, public as `is_auto_stream_key`, `split_auto_vs_ability`, `split_by_damage_type` | 125 |
| `src/calculator/empowered_swings.py` | `D-K` | an ability that empowers the next auto, and the swings its casts consumed | 5 defs: `_EmpoweredSwings`, `_empowered_swing_consumers`, ... `_recount_kept_crit_split` | 250 |
| `src/calculator/amp_chain.py` | `D-E` | which declared amplifier occupies each chain slot for this build, and how one amp's bonus is booked | `_amp_slot`, `_amp_slot_for`, `_required_amp_slot`, `_amplifier_delta_events`, `_record_amp_row` | 145 |
| `src/calculator/damage_amplifiers.py` | `D-D`, `D-F` | fight-wide amplifiers applied after the ledger: whole-total, Horizon Focus, Command, Expose Weakness | 6 defs: `_hypershot_delta_events`, `_apply_general_amplifiers`, ... `_add_expose_weakness` | 345 |
| `src/calculator/rune_amplifiers.py` | `D-G` | the two selected-rune amplifier shapes, health-gated and flat | 6 defs: `_health_gated_events`, `_health_gate_disclosure`, ... `_add_rune_flat_amp_damage` | 195 |
| `src/calculator/lethality_windows.py` | `D-H` | authored temporary lethality repricing later physical packets | `_apply_temporary_lethality_windows`, `_finite_numeric_receipt` | 190 |
| `src/calculator/stored_damage.py` | `D-I` | champion-owned stored damage resolved off the post-mitigation ledger | `_add_stored_damage` | 130 |
| `src/calculator/on_hit_healing.py` | `D-B` | item heals that ride a basic attack: authored on-hit receipts and Sundered Sky's first attack | `_add_on_hit_healing`, `_add_first_auto_healing` | 135 |
| `src/calculator/damage_reprice.py` | `D-C` | re-pricing a landed packet after the fact, and the mechanics that read the re-priced ledger | `_apply_liandry_reprice`, `_carry_declarations_onto_repriced_ticks`, `_add_shadowflame_cinderbloom` | 185 |
| `src/calculator/shield_outcome.py` | `D-O` | splitting post-mitigation damage into shield absorption and health damage | `_resolve_starting_shield_outcome`, `_walk_end_time`, `_ThresholdHealDrip` | 265 |
| `src/calculator/single_proc_on_hits.py` | `D-A` | items that proc once or on a stack counter rather than per hit | `_add_single_proc_on_hits`, `_add_copied_stacking_on_hit_packets` | 1115 |

67 rows against the plan's "about 55": `resource_admission.py` and `fight_cast_plan.py` are two maps' names for one resource band, `cast_slots.py`, `event_rows.py` and `single_proc_on_hits.py` each share a definition with a neighbouring module, and `stack_ledgers/` is seven champion files a coarser count reads as one.

75 modules shipped against these 67 rows. Eight are splits this roster does not name, each along a concept line a reader would use: `fight/autos/swing_profile.py` (what one swing carries, as opposed to when it lands), `fight/declarations.py` (what a build declares, off `FightState`'s field list), `fight/rotation/burst_autos.py` (the auto stream an empowered burst re-times), `fight/items/ultimate_procs.py` (the zone an ultimate cast opens), `fight/ledger/execute_stamps.py`, `fight/setup/shield_reaver.py`, `fight/after/execute_display.py` and `fight/after/fight_notes.py`.
