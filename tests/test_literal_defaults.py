"""Rule-5 lint: the scanned files read no cached data behind a literal default.

`scripts/literal_defaults.py` flags `.get("key", <literal>)`, `<get> or
<literal>` and `getattr(o, "attr", <literal>)`, exempting an index into a
local accumulator and a None-coalesce by shape.  What survives is frozen here
by module path, enclosing function and key — never by line number, so an edit
above a site does not turn this red.

`ROOTS` is the covered set: every `.py` under it is scanned, including the
ones that currently survive nothing, so a new literal default in a clean
champion module is caught the day it is written.  A file joins `ROOTS` only
once every site in it is either converted or sorted into a bucket below.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import literal_defaults  # noqa: E402  (path set above)

CALCULATOR = Path(__file__).resolve().parent.parent / "src" / "calculator"

#: Reads off an internal breakdown or damage-event row.  These rows have no
#: schema home the way `_damage_event_row`'s mandatory five do; one row
#: dataclass retires the whole list at once (campaign decision D3, bucket D1).
ROW_READS = frozenset(
    {
        ("damage.py", "_ability_dot_tick_events", "dict.get", '"casts"'),
        ("damage.py", "_ability_dot_tick_events", "dict.get", '"total_damage"'),
        ("damage.py", "_add_ashe_focus", "dict.get", '"slot"'),
        ("damage.py", "_add_ashe_focus", "or-default", '"auto_attacks"'),
        ("damage.py", "_add_ashe_focus", "or-default", '"damage_events"'),
        ("damage.py", "_add_aurelion_sol_stardust", "dict.get", '"ordinal"'),
        ("damage.py", "_add_aurelion_sol_stardust", "dict.get", '"slot"'),
        ("damage.py", "_add_aurelion_sol_stardust", "dict.get", '"time"'),
        ("damage.py", "_add_aurelion_sol_stardust", "or-default", '"ordinal"'),
        ("damage.py", "_add_copied_stacking_on_hit_packets", "dict.get", '"packets"'),
        ("damage.py", "_add_copied_stacking_on_hit_packets", "dict.get", '"time"'),
        ("damage.py", "_add_heimerdinger_w_e", "dict.get", '"raw_damage"'),
        ("damage.py", "_add_keystone_conqueror", "dict.get", '"reason"'),
        ("damage.py", "_add_keystone_conqueror", "dict.get", '"sequence"'),
        ("damage.py", "_add_keystone_dark_harvest", "dict.get", '"time"'),
        ("damage.py", "_add_keystone_deathfire", "dict.get", '"event_precision"'),
        ("damage.py", "_add_rengar_ferocity", "dict.get", '"detail"'),
        ("damage.py", "_add_rengar_ferocity", "dict.get", '"ordinal"'),
        ("damage.py", "_add_rengar_ferocity", "dict.get", '"reason"'),
        ("damage.py", "_add_rengar_ferocity", "dict.get", '"slot"'),
        ("damage.py", "_add_rengar_ferocity", "or-default", '"ordinal"'),
        ("damage.py", "_add_senna_souls", "dict.get", '"target"'),
        ("damage.py", "_add_single_proc_on_hits", "dict.get", '"event_precision"'),
        ("damage.py", "_add_spellblade_damage", "dict.get", '"casts"'),
        ("damage.py", "_add_stored_damage", "dict.get", '"casts"'),
        ("damage.py", "_add_stored_damage", "dict.get", '"slot"'),
        ("damage.py", "_add_stored_damage", "dict.get", '"time"'),
        ("damage.py", "_apply_command_amp", "or-default", '"damage_events"'),
        ("damage.py", "_apply_damage_amplifiers", "dict.get", '"total_damage"'),
        ("damage.py", "_apply_mana_resource_limits", "dict.get", '"burst_seconds"'),
        ("damage.py", "_apply_mana_resource_limits", "dict.get", '"window_seconds"'),
        (
            "damage.py",
            "_apply_temporary_lethality_windows",
            "dict.get",
            '"event_phase"',
        ),
        (
            "damage.py",
            "_apply_temporary_lethality_windows",
            "dict.get",
            '"total_damage"',
        ),
        ("damage.py", "_author_ability_dot_events", "dict.get", '"slot"'),
        ("damage.py", "_author_empowered_swing_events", "dict.get", '"damage"'),
        ("damage.py", "_author_empowered_swing_events", "dict.get", '"damage_type"'),
        ("damage.py", "_author_empowered_swing_events", "dict.get", '"total_damage"'),
        ("damage.py", "_conqueror_trigger_events", "dict.get", '"phase"'),
        ("damage.py", "_conqueror_trigger_events", "dict.get", '"slot"'),
        ("damage.py", "_conqueror_trigger_events", "dict.get", '"time"'),
        ("damage.py", "_damaging_cast_times", "dict.get", '"total_raw"'),
        ("damage.py", "_dark_harvest_trigger_event", "dict.get", '"phase"'),
        ("damage.py", "_deathfire_trigger_events", "dict.get", '"event_precision"'),
        ("damage.py", "_deathfire_trigger_events", "dict.get", '"slot"'),
        ("damage.py", "_deathfire_trigger_events", "dict.get", '"time"'),
        ("damage.py", "_empowered_swing_consumers", "dict.get", '"casts"'),
        ("damage.py", "_empowered_swing_consumers", "dict.get", '"slot"'),
        ("damage.py", "_event_timeline_coverage", "dict.get", '"casts"'),
        ("damage.py", "_event_timeline_coverage", "dict.get", '"event_precision"'),
        ("damage.py", "_event_timeline_coverage", "dict.get", '"total_damage"'),
        ("damage.py", "_feed_ashe_focus_stack", "dict.get", '"time"'),
        ("damage.py", "_feed_ashe_focus_stack", "or-default", '"time"'),
        ("damage.py", "_first_damaging_ability_event", "dict.get", '"event_precision"'),
        ("damage.py", "_first_damaging_ability_event", "dict.get", '"total_damage"'),
        ("damage.py", "_first_damaging_ability_event", "or-default", '"total_damage"'),
        ("damage.py", "_hypershot_delta_events", "dict.get", '"damage_type"'),
        ("damage.py", "_hypershot_delta_events", "dict.get", '"total_damage"'),
        ("damage.py", "_impaired_instance_times", "dict.get", '"total_raw"'),
        ("damage.py", "_item_proc_precision", "dict.get", '"casts"'),
        ("damage.py", "_item_proc_precision", "or-default", '"casts"'),
        ("damage.py", "_layer_on_hit_effects", "dict.get", '"casts"'),
        ("damage.py", "_muramana_cast_receipt", "dict.get", '"total_damage"'),
        ("damage.py", "_muramana_cast_receipt", "or-default", '"total_damage"'),
        ("damage.py", "_ordered_damage_events", "dict.get", '"casts"'),
        ("damage.py", "_ordered_damage_events", "dict.get", '"count"'),
        ("damage.py", "_ordered_damage_events", "dict.get", '"slot"'),
        ("damage.py", "_ordered_damage_events", "dict.get", '"time"'),
        ("damage.py", "_ordered_damage_events", "dict.get", '"total_damage"'),
        ("damage.py", "_ordered_damage_events", "dict.get", '"total_raw"'),
        ("damage.py", "_ordered_damage_events", "or-default", '"total_raw"'),
        ("damage.py", "_reattribute_empowered_swings", "dict.get", '"casts"'),
        ("damage.py", "_reattribute_empowered_swings", "dict.get", '"count"'),
        ("damage.py", "_reattribute_empowered_swings", "dict.get", '"damage_per_hit"'),
        (
            "damage.py",
            "_resolve_starting_shield_outcome",
            "dict.get",
            '"execute_threshold_ratio"',
        ),
        ("damage.py", "_resolve_starting_shield_outcome", "dict.get", '"raw_damage"'),
        ("damage.py", "_resolve_starting_shield_outcome", "dict.get", '"total_damage"'),
        (
            "damage.py",
            "_resolve_starting_shield_outcome",
            "or-default",
            '"execute_threshold_ratio"',
        ),
        ("damage.py", "_resolve_starting_shield_outcome", "or-default", '"raw_damage"'),
        ("damage.py", "_resource_ledger_public", "dict.get", '"bonus_delta"'),
        ("damage.py", "_resource_ledger_public", "or-default", '"bonus_delta"'),
        ("damage.py", "_return_denied_burst_budget", "dict.get", '"burst_seconds"'),
        ("damage.py", "_row_damage_parts", "dict.get", '"total_damage"'),
        ("damage.py", "_schedule_enlighten", "dict.get", '"tick"'),
        ("damage.py", "_self_shield_times", "dict.get", '"time"'),
        ("damage.py", "_shaped_charge_proc_receipts", "dict.get", '"event_precision"'),
        ("damage.py", "_slot_ordinals", "dict.get", '"ordinal"'),
        ("damage.py", "_slot_ordinals", "dict.get", '"slot"'),
        ("damage.py", "_slot_ordinals", "or-default", '"ordinal"'),
        ("damage.py", "_stacked_champion_proc_times", "dict.get", '"event_precision"'),
        ("damage.py", "_stacked_champion_proc_times", "dict.get", '"total_damage"'),
        ("damage.py", "add", "dict.get", '"cc_duration"'),
        ("damage.py", "add", "or-default", '"cc_duration"'),
        ("damage.py", "emit_until", "dict.get", '"category"'),
        ("damage.py", "emit_until", "dict.get", '"source"'),
        ("damage.py", "split_auto_vs_ability", "dict.get", '"total_damage"'),
        ("damage.py", "split_by_damage_type", "dict.get", '"total_damage"'),
    }
)

#: Request-supplied per-item state, not cached data: an absent key is the
#: item's declared off state, and `ITEM_INPUT_OPTIONS` owns what that is.
REQUEST_ITEM_STATE = frozenset(
    {
        (
            "item_effects.py",
            "actualizer_active_seconds",
            "dict.get",
            '"mana_made_real_active"',
        ),
        (
            "item_effects.py",
            "actualizer_active_seconds",
            "dict.get",
            '"mana_made_real_active_seconds"',
        ),
        (
            "item_effects.py",
            "actualizer_active_seconds",
            "or-default",
            '"mana_made_real_active"',
        ),
        ("item_effects.py", "input_option_crit_chance", "dict.get", '"crit_stacks"'),
        (
            "item_effects.py",
            "input_option_retribution_bonus_ad",
            "dict.get",
            '"missing_health_percent"',
        ),
        ("item_effects.py", "item_state_receipts", "dict.get", '"Endless Hunger"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"Heartsteel"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"Hubris"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"Knight\'s Vow"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"Rod of Ages"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"Tear of the Goddess"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"Yun Tal Wildarrows"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"bonus_health"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"crit_stacks"'),
        (
            "item_effects.py",
            "item_state_receipts",
            "dict.get",
            '"eminence_active_seconds"',
        ),
        ("item_effects.py", "item_state_receipts", "dict.get", '"eminence_stacks"'),
        (
            "item_effects.py",
            "item_state_receipts",
            "dict.get",
            '"feast_active_seconds"',
        ),
        (
            "item_effects.py",
            "item_state_receipts",
            "dict.get",
            '"holder_above_30_percent"',
        ),
        ("item_effects.py", "item_state_receipts", "dict.get", '"manaflow_bonus_mana"'),
        (
            "item_effects.py",
            "item_state_receipts",
            "dict.get",
            '"missing_health_percent"',
        ),
        ("item_effects.py", "item_state_receipts", "dict.get", '"shared_riches_gold"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"timeless_stacks"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"ward_uses"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"worthy_target_index"'),
        ("item_effects.py", "item_state_receipts", "dict.get", '"worthy_within_range"'),
        (
            "item_effects.py",
            "item_state_receipts",
            "or-default",
            '"Overlord\'s Bloodmail"',
        ),
        ("item_effects.py", "item_state_receipts", "or-default", '"crit_stacks"'),
        (
            "item_effects.py",
            "item_state_receipts",
            "or-default",
            '"eminence_active_seconds"',
        ),
        ("item_effects.py", "item_state_receipts", "or-default", '"eminence_stacks"'),
        (
            "item_effects.py",
            "item_state_receipts",
            "or-default",
            '"feast_active_seconds"',
        ),
        (
            "item_effects.py",
            "item_state_receipts",
            "or-default",
            '"shared_riches_gold"',
        ),
        ("item_effects.py", "item_state_receipts", "or-default", '"ward_uses"'),
    }
)

#: Reads on the in-module `ITEM_INPUT_OPTIONS` declaration itself.  An absent
#: facet means this option declares none, which is a source fact, not a
#: cached-data miss.
OPTION_SCHEMA = frozenset(
    {
        (
            "item_effects.py",
            "_input_option_stat_bonuses",
            "dict.get",
            '"bonus_ap_per_unit"',
        ),
        (
            "item_effects.py",
            "_input_option_stat_bonuses",
            "dict.get",
            '"bonus_health_per_unit"',
        ),
        (
            "item_effects.py",
            "_input_option_stat_bonuses",
            "dict.get",
            '"bonus_mana_per_unit"',
        ),
        ("item_effects.py", "_item_option_schemas", "dict.get", '"options"'),
        ("item_effects.py", "input_option_float_value", "dict.get", '"step"'),
        ("item_effects.py", "input_option_float_value", "or-default", '"step"'),
        ("item_effects.py", "validate_item_input_options", "dict.get", '"step"'),
        ("item_effects.py", "validate_item_input_options", "or-default", '"step"'),
    }
)

#: A loadout row's own name.  The empty string is a sentinel the next
#: statement rejects or skips past; no number rides on it.
LOADOUT_NAMES = frozenset(
    {
        ("item_effects.py", "_cached_sustain_stat", "or-default", '"name"'),
        ("item_effects.py", "_resolve_damage_effects_uncached", "dict.get", '"name"'),
        ("item_effects.py", "active_secondary_ad_item_name", "dict.get", '"name"'),
        ("item_effects.py", "cleave_on_hit_item_name", "dict.get", '"name"'),
        ("item_effects.py", "grouped_sustain_stat_percent", "or-default", '"name"'),
        ("item_effects.py", "hydra_secondary_item_name", "dict.get", '"name"'),
        ("item_effects.py", "resolve_damage_effects", "dict.get", '"name"'),
        ("item_effects.py", "target_class_denials", "dict.get", '"name"'),
        ("item_effects.py", "target_class_denials", "or-default", '"name"'),
    }
)

#: Atom rows compared against the registry.  The empty tuple is the failure
#: branch: each of these raises on the next line rather than using it.
ATOM_ROWS = frozenset(
    {
        ("item_effects.py", "counter_trigger", "dict.get", '"counter_trigger"'),
        (
            "item_effects.py",
            "dorans_helm_helping_hand_minion_damage",
            "dict.get",
            '"values"',
        ),
        (
            "item_effects.py",
            "guardian_angel_rebirth_declaration",
            "dict.get",
            '"values"',
        ),
        (
            "item_effects.py",
            "ionian_insight_summoner_spell_haste",
            "dict.get",
            '"values"',
        ),
        ("item_effects.py", "spell_shield_cooldown_seconds", "dict.get", '"values"'),
    }
)

#: Strict traversals of a raw cached ability row.  Every one of these feeds a
#: shape check whose failure branch raises, naming champion, slot and source —
#: the empty default is the path *to* that raise, never a served value.
WIKI_TRAVERSALS = frozenset(
    {
        ("ability_atoms.py", "_valid_atom_hash", "dict.get", '"hash"'),
        ("ability_atoms.py", "ranked_ability_atom_value", "dict.get", '"values"'),
        ("ability_atoms.py", "required_ability_atom", "dict.get", '"evidence"'),
        (
            "ability_atoms.py",
            "required_ranked_attribute_atom",
            "dict.get",
            '"abilities"',
        ),
        (
            "ability_atoms.py",
            "required_ranked_attribute_atom",
            "dict.get",
            '"attribute"',
        ),
        ("ability_atoms.py", "required_ranked_attribute_atom", "dict.get", '"effects"'),
        (
            "ability_atoms.py",
            "required_ranked_attribute_atom",
            "dict.get",
            '"leveling"',
        ),
        (
            "ability_atoms.py",
            "required_ranked_attribute_atom",
            "dict.get",
            '"modifiers"',
        ),
    }
)

#: The same traversal shape as `WIKI_TRAVERSALS`, over the whole covered set:
#: one step of a walk down a raw cached row (champion, item or rune JSON)
#: whose empty default is the path to the branch that refuses — a `return
#: None` that prices the slot at nothing, or a raise naming the source.  No
#: number is ever served from one of these defaults; the walk that would have
#: produced it does not run.  A site that *serves* a cached value belongs in
#: no bucket: it gets a fail-loud accessor instead (`slotlib.ability_name`,
#: `ability_atoms.required_ability_atom`, `item_effects`' typed readers).
CACHED_SOURCE_ROW = frozenset(
    {
        ("champions/aatrox.py", "derive_self_healing", "dict.get", '"description"'),
        ("champions/aatrox.py", "derive_self_healing", "dict.get", '"effects"'),
        (
            "champions/akshan.py",
            "_extract_double_shot_ratio",
            "dict.get",
            '"description"',
        ),
        ("champions/akshan.py", "_extract_double_shot_ratio", "dict.get", '"effects"'),
        (
            "champions/akshan.py",
            "_parse_passive_proc_damage",
            "dict.get",
            '"description"',
        ),
        ("champions/akshan.py", "_parse_passive_proc_damage", "dict.get", '"effects"'),
        ("champions/alistar.py", "_extract_e_on_hit_damage", "dict.get", '"attribute"'),
        ("champions/alistar.py", "_extract_e_on_hit_damage", "dict.get", '"effects"'),
        ("champions/alistar.py", "_extract_e_on_hit_damage", "dict.get", '"leveling"'),
        ("champions/alistar.py", "_extract_e_on_hit_damage", "dict.get", '"modifiers"'),
        ("champions/alistar.py", "_extract_e_on_hit_damage", "dict.get", '"values"'),
        ("champions/alistar.py", "derive_self_healing", "dict.get", '"description"'),
        ("champions/alistar.py", "derive_self_healing", "dict.get", '"effects"'),
        ("champions/ambessa.py", "_drakehounds_step", "dict.get", '"description"'),
        ("champions/ambessa.py", "_drakehounds_step", "dict.get", '"effects"'),
        ("champions/ambessa.py", "_parse_passive_damage", "dict.get", '"description"'),
        ("champions/ambessa.py", "_parse_passive_damage", "dict.get", '"effects"'),
        ("champions/ambessa.py", "_parse_passive_damage", "dict.get", '"modifiers"'),
        (
            "champions/ambessa.py",
            "_repudiation_shield_amount",
            "dict.get",
            '"modifiers"',
        ),
        ("champions/ambessa.py", "_repudiation_shield_amount", "dict.get", '"units"'),
        ("champions/ambessa.py", "_repudiation_shield_amount", "dict.get", '"values"'),
        ("champions/aphelios.py", "derive_self_healing", "dict.get", '"P"'),
        ("champions/aphelios.py", "derive_self_healing", "dict.get", '"abilities"'),
        ("champions/ashe.py", "_require_q_rows", "dict.get", '"effects"'),
        ("champions/ashe.py", "_require_q_rows", "dict.get", '"leveling"'),
        (
            "champions/attribute_classifier.py",
            "classify_damage_type",
            "dict.get",
            '"damageType"',
        ),
        (
            "champions/attribute_classifier.py",
            "classify_damage_type",
            "dict.get",
            '"effects"',
        ),
        (
            "champions/attribute_classifier.py",
            "classify_damage_type",
            "dict.get",
            '"leveling"',
        ),
        ("champions/azir.py", "_arise", "or-default", '"rechargeRate"'),
        ("champions/belveth.py", "_per_level_scaling", "dict.get", '"attribute"'),
        ("champions/belveth.py", "_per_level_scaling", "dict.get", '"effects"'),
        ("champions/belveth.py", "_per_level_scaling", "dict.get", '"leveling"'),
        ("champions/blitzcrank.py", "_static_field", "dict.get", '"attribute"'),
        ("champions/blitzcrank.py", "_static_field", "dict.get", '"effects"'),
        ("champions/blitzcrank.py", "_static_field", "dict.get", '"leveling"'),
        ("champions/blitzcrank.py", "_static_field", "dict.get", '"modifiers"'),
        ("champions/blitzcrank.py", "_static_field", "dict.get", '"units"'),
        (
            "champions/cassiopeia.py",
            "_bonus_magic_damage_levelings",
            "dict.get",
            '"effects"',
        ),
        (
            "champions/cassiopeia.py",
            "_bonus_magic_damage_levelings",
            "dict.get",
            '"leveling"',
        ),
        ("champions/darius.py", "_per_level", "dict.get", '"effects"'),
        ("champions/darius.py", "_per_level", "dict.get", '"leveling"'),
        ("champions/engine.py", "_stamp_slot_facts", "dict.get", '"spellEffects"'),
        ("champions/engine.py", "parse_abilities", "dict.get", '"abilities"'),
        ("champions/engine.py", "parse_abilities", "dict.get", '"resource"'),
        ("champions/gangplank.py", "_require_w_rows", "dict.get", '"effects"'),
        ("champions/gangplank.py", "_require_w_rows", "dict.get", '"leveling"'),
        ("champions/gangplank.py", "_require_w_rows", "dict.get", '"modifiers"'),
        ("champions/garen.py", "derive_self_healing", "dict.get", '"effects"'),
        ("champions/garen.py", "derive_self_healing", "dict.get", '"leveling"'),
        ("champions/garen.py", "derive_self_healing", "dict.get", '"modifiers"'),
        ("champions/garen.py", "derive_self_healing", "dict.get", '"values"'),
        ("champions/gragas.py", "derive_self_healing", "dict.get", '"description"'),
        ("champions/gragas.py", "derive_self_healing", "dict.get", '"effects"'),
        ("champions/gwen.py", "_snip_times", "dict.get", '"castTime"'),
        ("champions/heimerdinger.py", "_require_row", "dict.get", '"effects"'),
        ("champions/heimerdinger.py", "_require_row", "dict.get", '"leveling"'),
        ("champions/jayce.py", "_transform_ability", "dict.get", '"R"'),
        ("champions/karthus.py", "_defile_mana_per_second", "dict.get", '"modifiers"'),
        ("champions/karthus.py", "_defile_mana_per_second", "dict.get", '"values"'),
        ("champions/karthus.py", "_defile_mana_per_second", "or-default", '"cost"'),
        ("champions/ksante.py", "_require_row", "dict.get", '"effects"'),
        ("champions/ksante.py", "_require_row", "dict.get", '"leveling"'),
        ("champions/maokai.py", "derive_self_healing", "dict.get", '"modifiers"'),
        ("champions/maokai.py", "derive_self_healing", "dict.get", '"values"'),
        ("champions/maokai.py", "derive_self_healing", "or-default", '"cooldown"'),
        (
            "champions/mel.py",
            "_searing_brilliance_per_missile",
            "or-default",
            '"modifiers"',
        ),
        (
            "champions/mel.py",
            "_searing_brilliance_per_missile",
            "or-default",
            '"values"',
        ),
        (
            "champions/miss_fortune.py",
            "_love_tap_ad_ratio",
            "or-default",
            '"modifiers"',
        ),
        ("champions/miss_fortune.py", "_love_tap_ad_ratio", "or-default", '"values"'),
        ("champions/mordekaiser.py", "parse", "dict.get", '"description"'),
        ("champions/mordekaiser.py", "parse", "dict.get", '"effects"'),
        ("champions/ornn.py", "_temper_consume_percent", "or-default", '"description"'),
        ("champions/ornn.py", "_temper_consume_percent", "or-default", '"effects"'),
        ("champions/rengar.py", "_ferocity_bonus", "dict.get", '"description"'),
        ("champions/rengar.py", "_ferocity_bonus", "dict.get", '"effects"'),
        ("champions/sett.py", "_haymaker", "dict.get", '"modifiers"'),
        ("champions/sett.py", "_haymaker", "dict.get", '"units"'),
        ("champions/sett.py", "_haymaker", "dict.get", '"values"'),
        ("champions/sett.py", "_knuckle_down", "dict.get", '"modifiers"'),
        ("champions/sett.py", "_knuckle_down", "dict.get", '"units"'),
        ("champions/sett.py", "_knuckle_down", "dict.get", '"values"'),
        ("champions/sett.py", "derive_self_healing", "dict.get", '"description"'),
        ("champions/sett.py", "derive_self_healing", "dict.get", '"effects"'),
        ("champions/shen.py", "_ki_barrier_shield_amount", "dict.get", '"modifiers"'),
        ("champions/shen.py", "_ki_barrier_shield_amount", "dict.get", '"units"'),
        ("champions/shen.py", "_ki_barrier_shield_amount", "dict.get", '"values"'),
        ("champions/shen.py", "_named_level_rank_damage", "dict.get", '"effects"'),
        ("champions/shen.py", "_named_level_rank_damage", "dict.get", '"leveling"'),
        ("champions/shen.py", "_named_level_rank_damage", "dict.get", '"modifiers"'),
        ("champions/shen.py", "_named_level_rank_damage", "dict.get", '"units"'),
        ("champions/shen.py", "_named_level_rank_damage", "dict.get", '"values"'),
        (
            "champions/shyvana.py",
            "_scalemail_per_stack",
            "or-default",
            '"description"',
        ),
        ("champions/shyvana.py", "_scalemail_per_stack", "or-default", '"effects"'),
        (
            "champions/slotlib.py",
            "_find_primary_damage_leveling",
            "dict.get",
            '"attribute"',
        ),
        (
            "champions/slotlib.py",
            "_find_primary_damage_leveling",
            "dict.get",
            '"effects"',
        ),
        (
            "champions/slotlib.py",
            "_find_primary_damage_leveling",
            "dict.get",
            '"leveling"',
        ),
        ("champions/slotlib.py", "_modifier_value", "dict.get", '"modifiers"'),
        ("champions/slotlib.py", "_modifier_value", "dict.get", '"values"'),
        ("champions/slotlib.py", "_require_seconds", "dict.get", '"units"'),
        ("champions/slotlib.py", "extract_cooldown", "dict.get", '"values"'),
        (
            "champions/slotlib.py",
            "extract_description_control_durations",
            "or-default",
            '"description"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_control_durations",
            "or-default",
            '"effects"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_damage_reduction",
            "or-default",
            '"description"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_damage_reduction",
            "or-default",
            '"effects"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_damage_reduction_cap",
            "or-default",
            '"description"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_damage_reduction_cap",
            "or-default",
            '"effects"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_duration",
            "or-default",
            '"description"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_duration",
            "or-default",
            '"effects"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_invulnerability_timing",
            "or-default",
            '"description"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_invulnerability_timing",
            "or-default",
            '"effects"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_shield_duration",
            "or-default",
            '"description"',
        ),
        (
            "champions/slotlib.py",
            "extract_description_shield_duration",
            "or-default",
            '"effects"',
        ),
        ("champions/slotlib.py", "extract_recharge", "or-default", '"rechargeRate"'),
        ("champions/slotlib.py", "extract_resource_cost", "dict.get", '"modifiers"'),
        ("champions/slotlib.py", "extract_resource_cost", "dict.get", '"values"'),
        ("champions/slotlib.py", "extract_resource_cost", "or-default", '"cost"'),
        ("champions/slotlib.py", "find_named_leveling", "dict.get", '"attribute"'),
        ("champions/slotlib.py", "find_named_leveling", "dict.get", '"effects"'),
        ("champions/slotlib.py", "find_named_leveling", "dict.get", '"leveling"'),
        ("champions/slotlib.py", "parse", "or-default", '"targeting"'),
        ("champions/slotlib.py", "sum_modifiers", "dict.get", '"modifiers"'),
        ("champions/slotlib.py", "sum_modifiers", "dict.get", '"units"'),
        ("champions/slotlib.py", "sum_modifiers", "dict.get", '"values"'),
        ("champions/syndra.py", "_dark_sphere_second_charge", "dict.get", '"resource"'),
        ("champions/taric.py", "_bravado_window_terms", "dict.get", '"description"'),
        ("champions/taric.py", "_bravado_window_terms", "dict.get", '"effects"'),
        ("champions/taric.py", "_starlights_touch", "dict.get", '"description"'),
        ("champions/taric.py", "_starlights_touch", "dict.get", '"effects"'),
        ("champions/udyr.py", "_target_max_health_percent", "dict.get", '"modifiers"'),
        ("champions/udyr.py", "_target_max_health_percent", "dict.get", '"units"'),
        ("champions/udyr.py", "_target_max_health_percent", "dict.get", '"values"'),
        ("champions/vi.py", "_carry_blast_shield", "dict.get", '"description"'),
        ("champions/vi.py", "_carry_blast_shield", "dict.get", '"effects"'),
        ("champions/viktor.py", "_siphon_shield", "dict.get", '"modifiers"'),
        ("champions/viktor.py", "_siphon_shield", "dict.get", '"units"'),
        ("champions/viktor.py", "_siphon_shield", "dict.get", '"values"'),
        ("champions/xayah.py", "_bladecaller", "dict.get", '"values"'),
        (
            "champions/xayah.py",
            "_secondary_feather_crit_extra",
            "dict.get",
            '"description"',
        ),
        (
            "champions/xayah.py",
            "_secondary_feather_crit_extra",
            "dict.get",
            '"effects"',
        ),
        ("champions/xayah.py", "_secondary_feather_ratio", "dict.get", '"description"'),
        ("champions/xayah.py", "_secondary_feather_ratio", "dict.get", '"effects"'),
        (
            "champions/yasuo.py",
            "_per_target_lockout",
            "or-default",
            '"onTargetCdStatic"',
        ),
        ("champions/yasuo.py", "_q3_knockup_duration", "or-default", '"description"'),
        ("champions/yasuo.py", "_q3_knockup_duration", "or-default", '"effects"'),
        ("champions/yone.py", "_q3_knockup_duration", "or-default", '"description"'),
        ("champions/yone.py", "_q3_knockup_duration", "or-default", '"effects"'),
        ("champions/yorick.py", "_leveling_flat_at_level", "dict.get", '"effects"'),
        ("champions/yorick.py", "_leveling_flat_at_level", "dict.get", '"leveling"'),
        ("champions/yorick.py", "_leveling_flat_at_level", "dict.get", '"modifiers"'),
        ("champions/yorick.py", "_leveling_flat_at_level", "dict.get", '"units"'),
        ("champions/yorick.py", "_leveling_flat_at_level", "dict.get", '"values"'),
        ("champions/ziggs.py", "_short_fuse", "dict.get", '"cooldown"'),
        ("champions/ziggs.py", "_short_fuse", "dict.get", '"modifiers"'),
        ("champions/ziggs.py", "_short_fuse", "dict.get", '"values"'),
        (
            "champions/ziggs.py",
            "_short_fuse_refund_seconds",
            "dict.get",
            '"description"',
        ),
        ("champions/ziggs.py", "_short_fuse_refund_seconds", "dict.get", '"effects"'),
        ("data_fetcher.py", "_item_name_index", "dict.get", '"name"'),
        ("data_updater.py", "reparse_cached_rune_effects", "dict.get", '"options"'),
        ("data_updater.py", "rune_roster", "dict.get", '"runes"'),
        ("data_updater.py", "rune_roster", "dict.get", '"slots"'),
        ("economics_data.py", "sourced_combine_cost", "dict.get", '"combine_costs"'),
        ("economics_data.py", "sourced_combine_cost", "or-default", '"id"'),
        ("economics_data.py", "sourced_combine_cost", "or-default", '"name"'),
        ("economics_data.py", "sourced_sell_value", "dict.get", '"per_item_sell"'),
        ("economics_data.py", "sourced_sell_value", "or-default", '"id"'),
        ("economics_data.py", "sourced_sell_value", "or-default", '"name"'),
        ("economics_data.py", "sourced_total", "dict.get", '"per_item_sell"'),
        ("economics_data.py", "sourced_total", "or-default", '"id"'),
        ("healing_helpers.py", "ability_json", "dict.get", '"abilities"'),
        ("healing_helpers.py", "leveling_modifier", "dict.get", '"effects"'),
        ("healing_helpers.py", "leveling_modifier", "dict.get", '"leveling"'),
        ("healing_helpers.py", "leveling_modifier", "dict.get", '"modifiers"'),
        ("healing_helpers.py", "leveling_modifier", "dict.get", '"values"'),
        ("healing_helpers.py", "leveling_ratio", "dict.get", '"effects"'),
        ("healing_helpers.py", "leveling_ratio", "dict.get", '"leveling"'),
        ("healing_helpers.py", "leveling_ratio", "dict.get", '"modifiers"'),
        ("healing_helpers.py", "leveling_ratio", "dict.get", '"units"'),
        ("healing_helpers.py", "leveling_ratio", "dict.get", '"values"'),
        ("healing_helpers.py", "leveling_value", "dict.get", '"effects"'),
        ("healing_helpers.py", "leveling_value", "dict.get", '"leveling"'),
        ("healing_helpers.py", "leveling_value", "dict.get", '"modifiers"'),
        ("healing_helpers.py", "leveling_value", "dict.get", '"values"'),
        ("interpreters/__init__.py", "uncompilable_item_receipt", "dict.get", '"name"'),
        (
            "interpreters/delta_amp.py",
            "resolve_static_holder_amps",
            "dict.get",
            '"name"',
        ),
        ("interpreters/reactive.py", "thorns_effects", "dict.get", '"name"'),
        ("item_coverage.py", "is_unreviewed_fixture", "dict.get", '"name"'),
        ("item_coverage.py", "optimizer_candidate_coverage", "dict.get", '"name"'),
        ("item_coverage.py", "optimizer_supported_items", "dict.get", '"name"'),
        ("item_coverage.py", "require_calculation_item_coverage", "dict.get", '"name"'),
        ("item_coverage.py", "require_certified_target_timeline", "dict.get", '"name"'),
        ("item_coverage.py", "require_optimizer_item_coverage", "dict.get", '"name"'),
        ("item_coverage.py", "target_item_model_coverage", "dict.get", '"name"'),
        ("item_source.py", "_champion_restriction", "or-default", '"champion"'),
        ("item_source.py", "_champion_restriction", "or-default", "key"),
        ("item_source.py", "_merge_effect_branches", "or-default", '"branches"'),
        ("item_source.py", "_merge_effect_branches", "or-default", '"effects"'),
        ("item_source.py", "_merge_one_item", "or-default", '"spec"'),
        ("item_source.py", "audit_scope", "or-default", "'name'"),
        ("item_source.py", "branch_inventory", "or-default", '"name"'),
        ("item_source.py", "branch_losses", "dict.get", "label"),
        ("item_source.py", "effect_entries", "or-default", '"active"'),
        ("item_source.py", "effect_entries", "or-default", '"passives"'),
        ("item_source.py", "item_source_audit", "or-default", '"name"'),
        ("item_source.py", "item_source_audit", "or-default", '"sourceWarnings"'),
        ("item_source.py", "merge_item_sources", "dict.get", 'item.get("id")'),
        ("item_source.py", "riot_declared_effects", "or-default", '"riotDescription"'),
        ("item_source.py", "sr_availability", "dict.get", '"purchasable"'),
        ("item_source.py", "sr_availability", "or-default", '"acquisitionNote"'),
        ("item_source.py", "sr_availability", "or-default", '"championRestriction"'),
        ("item_source.py", "sr_availability", "or-default", '"modes"'),
        ("item_source.py", "sr_availability", "or-default", '"name"'),
        ("item_source.py", "sr_availability", "or-default", '"prices"'),
        ("item_source.py", "sr_availability", "or-default", '"rank"'),
        ("item_source.py", "sr_availability", "or-default", '"shop"'),
        ("passive_parser.py", "_find_active_by_name", "dict.get", '"active"'),
        ("passive_parser.py", "_find_active_by_name", "or-default", '"name"'),
        ("passive_parser.py", "_find_item_data_by_name", "dict.get", '"name"'),
        ("passive_parser.py", "_find_passive_by_name", "dict.get", '"passives"'),
        ("passive_parser.py", "_find_passive_by_name", "or-default", '"name"'),
        (
            "passive_parser.py",
            "parse_item_effect",
            "dict.get",
            '"criticalStrikeDamage"',
        ),
        ("passive_parser.py", "parse_item_effect", "dict.get", '"percent"'),
        ("passive_parser.py", "parse_item_effect", "dict.get", '"stats"'),
        ("rune_effects.py", "_shard_row", "dict.get", '"row"'),
        ("rune_effects.py", "_shard_row", "dict.get", '"slots"'),
        ("rune_effects.py", "_shard_row_options", "dict.get", '"options"'),
        ("rune_effects.py", "_shard_rows", "dict.get", '"row"'),
        ("rune_effects.py", "_shard_rows", "dict.get", '"slots"'),
        ("rune_effects.py", "_slot_word", "dict.get", '"row"'),
        ("rune_effects.py", "cached_effects", "dict.get", '"effects"'),
        ("rune_effects.py", "shard_catalog", "dict.get", '"name"'),
        ("rune_effects.py", "shard_catalog", "dict.get", '"options"'),
        ("rune_effects.py", "shard_catalog", "dict.get", '"row"'),
        ("rune_effects.py", "shard_catalog", "dict.get", '"slots"'),
        ("rune_effects.py", "validate_keystone_options", "dict.get", '"options"'),
        ("rune_parser.py", "_certify_roster_agreement", "dict.get", '"path"'),
        ("rune_parser.py", "_certify_roster_agreement", "dict.get", '"slot"'),
        ("rune_parser.py", "_parse_leveling", "dict.get", '"type"'),
        ("rune_parser.py", "rune_payload", "dict.get", "key"),
        ("stats.py", "_validate_cached_item_stats", "or-default", '"name"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"adaptiveType"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"attackSpeedRatio"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"attackType"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"flat"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"healthRegen"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"mana"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"manaRegen"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"perLevel"'),
        ("stats.py", "champion_stat_conversion", "dict.get", '"name"'),
        ("stats.py", "get_flat", "dict.get", '"flat"'),
        ("stats.py", "get_item_stats", "dict.get", '"name"'),
        ("stats.py", "get_item_stats", "dict.get", '"stats"'),
        ("stats.py", "get_item_stats", "or-default", '"name"'),
        ("stats.py", "get_percent", "dict.get", '"percent"'),
    }
)

#: A read on something this repository authored, not something it ingested:
#: the entry a slot parser just built, a champion module's reviewed packet
#: spec, an in-module lookup table.  An absent key is that declaration's own
#: statement that it carries no such facet, which is the shape
#: `ability_atoms.ABILITY_PAYLOAD_SCHEMA` formalises for the payloads that
#: cross a module boundary.
AUTHORED_DECLARATION = frozenset(
    {
        ("champions/__init__.py", "get_champion_option_rotation", "dict.get", '"key"'),
        ("champions/ambessa.py", "_public_execution", "dict.get", '"parts"'),
        ("champions/ambessa.py", "_repudiation", "dict.get", '"name"'),
        ("champions/ambessa.py", "_repudiation", "dict.get", '"rank"'),
        ("champions/ambessa.py", "_repudiation", "or-default", '"rank"'),
        ("champions/amumu.py", "_apply_curse", "dict.get", '"parts"'),
        ("champions/aphelios.py", "parse", "dict.get", '"parts"'),
        ("champions/blitzcrank.py", "_rocket_grab", "dict.get", '"rank"'),
        ("champions/blitzcrank.py", "_rocket_grab", "or-default", '"rank"'),
        ("champions/camille.py", "_tactical_sweep_with_shield", "dict.get", '"rank"'),
        ("champions/camille.py", "_tactical_sweep_with_shield", "or-default", '"rank"'),
        ("champions/engine.py", "_apply_module_cc", "or-default", '"control_events"'),
        ("champions/engine.py", "_apply_module_cc", "or-default", '"parts"'),
        ("champions/engine.py", "_certify_shared_instant", "or-default", '"parts"'),
        ("champions/engine.py", "_empower_marker_part", "dict.get", '"damage_type"'),
        ("champions/engine.py", "_refuse_undeclared_part_cc", "or-default", '"parts"'),
        ("champions/engine.py", "_validate_cc_event_contract", "or-default", '"parts"'),
        ("champions/engine.py", "_validate_entry_keys", "dict.get", '"post_hit_proc"'),
        ("champions/engine.py", "_validate_entry_keys", "dict.get", '"target_debuff"'),
        (
            "champions/engine.py",
            "_validate_entry_keys",
            "or-default",
            '"post_hit_proc"',
        ),
        ("champions/evelynn.py", "_allure", "dict.get", '"skillshot"'),
        ("champions/leblanc.py", "_mimic", "dict.get", "choice"),
        ("champions/malphite.py", "parse", "dict.get", '"rank"'),
        ("champions/malphite.py", "parse", "or-default", '"rank"'),
        ("champions/module_contract.py", "coverage", "dict.get", "slot"),
        ("champions/module_helpers.py", "parse", "dict.get", '"parts"'),
        ("champions/mordekaiser.py", "parse", "dict.get", "'detail'"),
        ("champions/nidalee.py", "parse", "dict.get", '"detail"'),
        ("champions/nidalee.py", "parse", "dict.get", '"total_raw"'),
        ("champions/packet_module.py", "_apply_packet_tick_fix", "dict.get", '"count"'),
        (
            "champions/packet_module.py",
            "_apply_packet_tick_fix",
            "dict.get",
            '"damage_type"',
        ),
        (
            "champions/packet_module.py",
            "_apply_packet_tick_fix",
            "dict.get",
            '"total_raw"',
        ),
        ("champions/packet_module.py", "_apply_packet_tick_fix", "dict.get", "'name'"),
        (
            "champions/packet_module.py",
            "_apply_packet_tick_fix",
            "dict.get",
            "'tick_interval'",
        ),
        (
            "champions/packet_module.py",
            "_apply_packet_tick_fix",
            "or-default",
            '"total_raw"',
        ),
        ("champions/packet_module.py", "_compiled_slot", "dict.get", '"damage_type"'),
        ("champions/packet_module.py", "_compiled_slot", "dict.get", '"name"'),
        ("champions/packet_module.py", "_compiled_slot", "dict.get", '"ranks"'),
        ("champions/packet_module.py", "_compiled_slot", "dict.get", '"reason"'),
        ("champions/packet_module.py", "_one_hit", "dict.get", '"count"'),
        ("champions/packet_module.py", "_override_packet_static", "dict.get", '"base"'),
        (
            "champions/packet_module.py",
            "_override_packet_static",
            "dict.get",
            '"ratios"',
        ),
        ("champions/packet_module.py", "_override_packet_static", "dict.get", '"stat"'),
        (
            "champions/packet_module.py",
            "_override_packet_static",
            "dict.get",
            '"values"',
        ),
        ("champions/packet_module.py", "_single_hit_row", "dict.get", '"variants"'),
        ("champions/packet_module.py", "_variant_parsers", "dict.get", '"damage_type"'),
        ("champions/packet_module.py", "_variant_parsers", "dict.get", '"name"'),
        ("champions/packet_module.py", "_variant_parsers", "dict.get", '"ranks"'),
        ("champions/packet_module.py", "_variant_parsers", "dict.get", '"reason"'),
        ("champions/packet_module.py", "_variant_slot", "dict.get", '"default"'),
        (
            "champions/packet_module.py",
            "build_packet_module",
            "dict.get",
            '"assumptions"',
        ),
        ("champions/packet_module.py", "build_packet_module", "dict.get", '"slots"'),
        ("champions/packet_module.py", "build_packet_module", "dict.get", "'slots'"),
        ("champions/packet_module.py", "parse", "dict.get", '"base"'),
        ("champions/packet_module.py", "parse", "dict.get", '"count"'),
        ("champions/packet_module.py", "parse", "dict.get", '"damage_type"'),
        ("champions/packet_module.py", "parse", "dict.get", '"ratios"'),
        ("champions/packet_module.py", "parse", "dict.get", '"stat"'),
        ("champions/packet_module.py", "parse", "dict.get", '"total_multiplier"'),
        ("champions/packet_module.py", "parse", "dict.get", '"values"'),
        ("champions/packet_module.py", "parse", "dict.get", "'tick_interval'"),
        ("champions/packet_module.py", "parse_abilities", "dict.get", '"damage_type"'),
        ("champions/packet_module.py", "parse_abilities", "or-default", '"on_hit"'),
        ("champions/packet_module.py", "select_variant", "dict.get", '"default"'),
        ("champions/rakan.py", "_q_with_p_shield", "dict.get", '"rank"'),
        ("champions/rakan.py", "_q_with_p_shield", "or-default", '"rank"'),
        ("champions/samira.py", "parse", "dict.get", "'detail'"),
        ("champions/senna.py", "parse", "dict.get", '"name"'),
        ("champions/senna.py", "parse", "dict.get", '"rank"'),
        ("champions/senna.py", "parse", "or-default", '"rank"'),
        ("champions/shyvana.py", "derive_self_healing", "dict.get", '"detail"'),
        ("champions/slotlib.py", "parse", "dict.get", '"control_events"'),
        ("champions/slotlib.py", "parse", "dict.get", '"control_source_atoms"'),
        ("champions/slotlib.py", "parse", "dict.get", '"parts"'),
        ("champions/slotlib.py", "parse", "or-default", '"parts"'),
        ("champions/slotlib.py", "parse", "or-default", '"total_raw"'),
        ("champions/smolder.py", "parse", "dict.get", '"total_raw"'),
        ("champions/swain.py", "parse", "or-default", '"parts"'),
        ("champions/sylas.py", "parse", "or-default", '"parts"'),
        ("champions/teemo.py", "parse", "dict.get", '"detail"'),
        ("champions/teemo.py", "parse", "dict.get", '"total_raw"'),
        ("champions/vex.py", "parse", "dict.get", '"name"'),
        ("champions/vex.py", "parse", "dict.get", '"rank"'),
        ("champions/vex.py", "parse", "or-default", '"rank"'),
        ("champions/vi.py", "_carry_blast_shield", "dict.get", "'detail'"),
        ("champions/viktor.py", "parse", "dict.get", '"name"'),
        ("champions/viktor.py", "parse", "dict.get", '"rank"'),
        ("champions/viktor.py", "parse", "or-default", '"rank"'),
        ("champions/vladimir.py", "_apply_hemoplague", "dict.get", '"parts"'),
        ("champions/volibear.py", "parse", "dict.get", '"name"'),
        ("champions/volibear.py", "parse", "dict.get", '"rank"'),
        ("champions/volibear.py", "parse", "or-default", '"rank"'),
        (
            "champions/warwick.py",
            "derive_self_healing",
            "or-default",
            '"self_heal_share_of_damage"',
        ),
        ("champions/zac.py", "parse", "or-default", '"parts"'),
        ("champions/zed.py", "_death_mark", "dict.get", '"total_raw"'),
        ("champions/zed.py", "_death_mark", "or-default", '"total_raw"'),
        ("champions/zilean.py", "parse", "or-default", '"parts"'),
        ("champions/zoe.py", "_spell_thief", "dict.get", "summoner"),
        ("data_updater.py", "_riot_item_descriptions", "or-default", '"description"'),
        ("data_updater.py", "reparse_cached_rune_effects", "dict.get", '"slots"'),
        ("healing_helpers.py", "parsed_rank", "dict.get", '"rank"'),
        ("healing_helpers.py", "parsed_rank", "dict.get", "slot"),
        ("healing_helpers.py", "parsed_rank", "or-default", '"rank"'),
        ("item_coverage.py", "_declared_families", "dict.get", '"type"'),
        ("item_coverage.py", "review_issue_refs", "dict.get", "str(item_name)"),
        ("item_source.py", "_effect_name", "or-default", '"name"'),
        ("item_source.py", "_merge_one_item", "or-default", '"name"'),
        ("item_source.py", "branch_inventory", "or-default", "'name'"),
        ("item_source.py", "branches", "or-default", '"branches"'),
        ("item_source.py", "item_source_audit", "or-default", '"name"'),
        ("rune_effects.py", "rune_catalog", "dict.get", '"icon"'),
        ("rune_effects.py", "rune_catalog", "dict.get", '"path"'),
        ("rune_paths/domination.py", "_compile_cheap_shot", "dict.get", '"effects"'),
        ("rune_paths/domination.py", "_compile_sudden_impact", "dict.get", '"effects"'),
        (
            "rune_paths/domination.py",
            "_compile_taste_of_blood",
            "dict.get",
            '"effects"',
        ),
        (
            "rune_paths/domination.py",
            "_compile_ultimate_hunter",
            "dict.get",
            '"effects"',
        ),
        (
            "rune_paths/inspiration.py",
            "_compile_jack_of_all_trades",
            "dict.get",
            '"effects"',
        ),
        ("rune_paths/keystones.py", "_compile_aftershock", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_arcane_comet", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_conqueror", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_dark_harvest", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_deathfire", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_electrocute", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_first_strike", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_fleet", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_glacial", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_grasp", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_guardian", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_hail_of_blades", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_lethal_tempo", "dict.get", '"effects"'),
        (
            "rune_paths/keystones.py",
            "_compile_press_the_attack",
            "dict.get",
            '"effects"',
        ),
        ("rune_paths/keystones.py", "_compile_stormraider", "dict.get", '"effects"'),
        ("rune_paths/keystones.py", "_compile_summon_aery", "dict.get", '"effects"'),
        ("rune_paths/precision.py", "_compile_absorb_life", "dict.get", '"effects"'),
        ("rune_paths/precision.py", "_compile_last_stand", "dict.get", '"effects"'),
        (
            "rune_paths/precision.py",
            "_compile_legend_alacrity",
            "dict.get",
            '"effects"',
        ),
        (
            "rune_paths/precision.py",
            "_compile_legend_bloodline",
            "dict.get",
            '"effects"',
        ),
        ("rune_paths/precision.py", "_compile_legend_haste", "dict.get", '"effects"'),
        ("rune_paths/precision.py", "_compile_triumph", "dict.get", '"effects"'),
        ("rune_paths/resolve.py", "_compile_font_of_life", "dict.get", '"effects"'),
        ("rune_paths/resolve.py", "_compile_overgrowth", "dict.get", '"effects"'),
        ("rune_paths/resolve.py", "_compile_shield_bash", "dict.get", '"effects"'),
        ("rune_paths/shards.py", "compile_shard", "dict.get", '"effects"'),
        ("rune_paths/sorcery.py", "_compile_absolute_focus", "dict.get", '"effects"'),
        ("rune_paths/sorcery.py", "_compile_axiom_arcanist", "dict.get", '"effects"'),
        ("rune_paths/sorcery.py", "_compile_celerity", "dict.get", '"effects"'),
        ("rune_paths/sorcery.py", "_compile_gathering_storm", "dict.get", '"effects"'),
        ("rune_paths/sorcery.py", "_compile_scorch", "dict.get", '"effects"'),
        ("rune_paths/sorcery.py", "_compile_transcendence", "dict.get", '"effects"'),
        ("rune_paths/sorcery.py", "_compile_waterwalking", "dict.get", '"effects"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"ability_haste"'),
        ("stats.py", "calculate_total_stats", "dict.get", '"ability_power"'),
    }
)

#: A row the engine built during this fight — a damage event, a cast, a heal
#: payment, a stat block `calculate_total_stats` produced.  Same class as
#: `ROW_READS`, and it retires the same way: one row dataclass per producer.
#: A build-stat read is *not* in here when a declared vocabulary covers it —
#: `champions.inputs.champion_stat` is the accessor, and rune, interpreter
#: and champion formulas all go through it.
ENGINE_ROW = frozenset(
    {
        ("champions/aatrox.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/aatrox.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/alistar.py", "derive_self_healing", "dict.get", '"stacks"'),
        ("champions/alistar.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/alistar.py", "derive_self_healing", "or-default", '"stacks"'),
        ("champions/ambessa.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/ambessa.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/aphelios.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/briar.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/briar.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/briar.py", "derive_self_healing", "or-default", '"damage"'),
        ("champions/briar.py", "derive_self_healing", "or-default", '"raw_damage"'),
        ("champions/camille.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/camille.py", "derive_self_healing", "or-default", '"damage"'),
        ("champions/camille.py", "derive_self_healing", "or-default", '"raw_damage"'),
        ("champions/chogath.py", "derive_self_healing", "dict.get", '"amount"'),
        ("champions/chogath.py", "derive_self_healing", "dict.get", '"kills"'),
        ("champions/chogath.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/chogath.py", "derive_self_healing", "or-default", '"amount"'),
        ("champions/chogath.py", "derive_self_healing", "or-default", '"kills"'),
        ("champions/darius.py", "derive_self_healing", "dict.get", '"sequence"'),
        ("champions/darius.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/darius.py", "derive_self_healing", "or-default", '"sequence"'),
        ("champions/dr_mundo.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/fiddlesticks.py", "derive_self_healing", "dict.get", '"damage"'),
        (
            "champions/fiddlesticks.py",
            "derive_self_healing",
            "or-default",
            '"raw_damage"',
        ),
        ("champions/gangplank.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/gragas.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/gwen.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/hecarim.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/hecarim.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/illaoi.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/janna.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/karma.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/kindred.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/maokai.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/milio.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/mordekaiser.py", "derive_self_healing", "dict.get", '"amount"'),
        ("champions/mordekaiser.py", "derive_self_healing", "or-default", '"amount"'),
        ("champions/morgana.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/nasus.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/nidalee.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/nilah.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/nunu_willump.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/rakan.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/reksai.py", "derive_self_healing", "dict.get", '"amount"'),
        ("champions/reksai.py", "derive_self_healing", "or-default", '"amount"'),
        ("champions/shyvana.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/shyvana.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/sona.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/soraka.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/sylas.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/sylas.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/tahm_kench.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/taric.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/trundle.py", "derive_self_healing", "dict.get", '"amount"'),
        ("champions/trundle.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/trundle.py", "derive_self_healing", "dict.get", '"deaths"'),
        ("champions/trundle.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/trundle.py", "derive_self_healing", "or-default", '"amount"'),
        ("champions/trundle.py", "derive_self_healing", "or-default", '"deaths"'),
        ("champions/trundle.py", "derive_self_healing", "or-default", '"raw_damage"'),
        ("champions/udyr.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/vi.py", "_denting_stream", "dict.get", '"E"'),
        ("champions/vi.py", "_denting_stream", "dict.get", '"Q"'),
        ("champions/vladimir.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/vladimir.py", "derive_self_healing", "or-default", '"raw_damage"'),
        ("champions/volibear.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/warwick.py", "derive_self_healing", "dict.get", '"damage"'),
        ("champions/xin_zhao.py", "derive_self_healing", "dict.get", '"damage"'),
        (
            "champions/xin_zhao.py",
            "derive_self_healing",
            "or-default",
            '"stacks_required"',
        ),
        ("champions/yorick.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/yuumi.py", "derive_self_healing", "dict.get", '"time"'),
        ("champions/zac.py", "derive_self_healing", "dict.get", '"time"'),
        ("healing_helpers.py", "cast_slot_times", "dict.get", '"time"'),
        ("healing_helpers.py", "event_source", "dict.get", '"source_key"'),
        ("healing_helpers.py", "heal_from_damage", "dict.get", '"damage"'),
        ("healing_helpers.py", "heal_from_damage", "dict.get", '"time"'),
        ("healing_helpers.py", "payments", "dict.get", '"damage"'),
        ("healing_helpers.py", "payments", "dict.get", '"time"'),
        ("healing_helpers.py", "payments", "or-default", '"damage"'),
        ("healing_helpers.py", "trigger_fields", "dict.get", '"time"'),
        (
            "item_coverage.py",
            "require_certified_target_timeline",
            "dict.get",
            '"coarse_sources"',
        ),
        (
            "item_coverage.py",
            "require_certified_target_timeline",
            "dict.get",
            '"complete"',
        ),
        (
            "stats.py",
            "calculate_total_stats",
            "dict.get",
            '"armor_penetration_bonus_percent"',
        ),
        ("stats.py", "get_champion_base_stats", "dict.get", '"attackSpeedRatio"'),
    }
)

#: `getattr(module, "DECLARATION", None)` on a champion module, its parser,
#: or a compiled part.  The absent value is the module declining to declare
#: an optional contract, which `champions.module_contract` owns and validates;
#: it is a source fact about that module, not a cached-data miss.
MODULE_DECLARATION = frozenset(
    {
        ("champions/__init__.py", "get_champion_cast_order", "getattr", '"CAST_ORDER"'),
        (
            "champions/__init__.py",
            "get_custom_cast_order_unavailable_reason",
            "getattr",
            '"CUSTOM_CAST_ORDER_UNAVAILABLE_REASON"',
        ),
        ("champions/ambessa.py", "<module>", "getattr", '"phase"'),
        ("champions/engine.py", "_apply_module_cc", "getattr", '"cc_kind"'),
        ("champions/engine.py", "_refuse_undeclared_part_cc", "getattr", '"cc_kind"'),
        (
            "champions/engine.py",
            "_validate_cc_event_contract",
            "getattr",
            '"cc_duration"',
        ),
        ("champions/engine.py", "_validate_cc_event_contract", "getattr", '"cc_kind"'),
        (
            "champions/module_contract.py",
            "_cast_dependencies",
            "getattr",
            '"CAST_ORDER"',
        ),
        (
            "champions/module_contract.py",
            "_coverage_channels",
            "getattr",
            '"COVERAGE_CHANNELS"',
        ),
        ("champions/module_contract.py", "_module_cc", "getattr", '"MODULE_CC"'),
        ("champions/module_contract.py", "_module_cc", "getattr", '"cc_kinds"'),
        ("champions/module_contract.py", "_module_cc", "getattr", '"packet_sha256"'),
        (
            "champions/module_contract.py",
            "_packet_declaration",
            "getattr",
            '"packet_sha256"',
        ),
        ("champions/module_contract.py", "_present", "getattr", "attribute"),
        ("champions/module_contract.py", "_require_list", "getattr", "field_name"),
        (
            "champions/module_contract.py",
            "_stat_conversion",
            "getattr",
            '"MODULE_STAT_CONVERSION"',
        ),
        (
            "champions/module_contract.py",
            "_ultimate_recasts",
            "getattr",
            '"ULTIMATE_RECASTS"',
        ),
        (
            "champions/module_contract.py",
            "contract_from_module",
            "getattr",
            '"MODULE_COVERAGE"',
        ),
        ("champions/module_contract.py", "contract_from_module", "getattr", '"SLOTS"'),
        (
            "champions/module_contract.py",
            "contract_from_module",
            "getattr",
            '"parse_abilities"',
        ),
        ("champions/nocturne.py", "_tether_fear", "getattr", '"phase"'),
        ("champions/packet_module.py", "_variant_slot", "getattr", '"phase"'),
        ("data_updater.py", "_process_champions", "getattr", '"name"'),
        (
            "interpreters/__init__.py",
            "_validate_authority_agreement",
            "getattr",
            '"subject"',
        ),
        ("interpreters/cast_proc.py", "self_shield_owners", "getattr", '"self_shield"'),
        ("interpreters/defense_state.py", "_policy_reference", "getattr", "name"),
        ("item_coverage.py", "_prices_holder_durability", "getattr", "field"),
    }
)

#: The covered set: files and directories every `.py` under which is
#: scanned.  The rest of `src/calculator` is the declared tail (ER5).
ROOTS = (
    "damage.py",
    "item_effects.py",
    "ability_atoms.py",
    "champions",
    "rune_paths",
    "interpreters",
    "rune_effects.py",
    "rune_parser.py",
    "item_source.py",
    "item_coverage.py",
    "healing_helpers.py",
    "economics_data.py",
    "data_fetcher.py",
    "data_updater.py",
    "passive_parser.py",
    "stats.py",
    "__init__.py",
    "ability_spec.py",
    "application_errors.py",
    "capabilities.py",
    "cast_dependency.py",
    "coverage_evidence.py",
    "data_registry.py",
    "item_outcomes.py",
    "patch_identity.py",
    "program/__init__.py",
    "program/amp.py",
    "program/dependency.py",
    "program/identity.py",
    "program/precision.py",
    "program/route.py",
    "program/scope.py",
    "program/views/breakdown.py",
    "program/views/tdd.py",
    "request_parsing.py",
    "resistance.py",
    "role_quests.py",
    "shield_ledger.py",
    "stat_conversion.py",
    "survival/__init__.py",
    "survival/accumulate.py",
    "survival/pricing.py",
    "value_ref.py",
    "work_counters.py",
)

#: The declared tail (backlog ER5): every `src/calculator` module the pin
#: does not reach yet.  These are the request, timeline, program and
#: survival layers, whose surviving sites are overwhelmingly engine rows —
#: the `ROW_READS` class, which retires with a row dataclass per producer
#: rather than one conversion at a time.  A file leaves this tuple by
#: joining `ROOTS`; nothing may be added to it without a decision.
TAIL = (
    "ally_effects.py",
    "atomizer.py",
    "atomizer_domains.py",
    "auto_attack_policy.py",
    "bis.py",
    "calculate.py",
    "certainty.py",
    "cleanse_eligibility.py",
    "crowd_control_eligibility.py",
    "defensive_effects.py",
    "delivery_eligibility.py",
    "economy.py",
    "healing.py",
    "healing_reduction.py",
    "interaction_effects.py",
    "item_behavior.py",
    "item_behavior_catalog.py",
    "item_support_effects.py",
    "ledger_projection.py",
    "loadout_rules.py",
    "optimizer.py",
    "participant_timeline.py",
    "pipeline.py",
    "practice_dummy.py",
    "program/build.py",
    "program/caches.py",
    "program/compile.py",
    "program/events.py",
    "program/rung.py",
    "program/views/__init__.py",
    "program/views/receipt.py",
    "program/views/score.py",
    "program/views/survival.py",
    "program/walk.py",
    "public_response.py",
    "resource_ledger.py",
    "roster_composition.py",
    "rotation_resolver.py",
    "scenario.py",
    "spatial.py",
    "state_lifecycle.py",
    "support_effects.py",
    "survival/actions.py",
    "survival/compile.py",
    "survival/outcome_state.py",
    "survival/receipt_state.py",
    "survival/score_state.py",
    "survival/transitions.py",
    "timeline_coverage.py",
    "trigger_stream.py",
    "validation_receipts.py",
)

#: Every bucket, and the covered set they must exactly account for.
SURVIVORS = (
    ROW_READS
    | REQUEST_ITEM_STATE
    | OPTION_SCHEMA
    | LOADOUT_NAMES
    | ATOM_ROWS
    | WIKI_TRAVERSALS
    | CACHED_SOURCE_ROW
    | AUTHORED_DECLARATION
    | ENGINE_ROW
    | MODULE_DECLARATION
)

#: Receivers that carry a champion-module-authored ability payload.  A literal
#: default on one of these is what `ability_atoms.ABILITY_PAYLOAD_SCHEMA`
#: exists to refuse, so the count is pinned at zero rather than allowlisted.
PAYLOAD_RECEIVERS = (
    "ability.",
    "ability_damages",
    "ability_info",
    "auto_attack_override.",
    "conversion_info.",
    "crit_modifier.",
    "debuff.",
    "info.",
    "on_hit.",
    "on_hit_data.",
    "on_hit_spec.",
    "r_info.",
    "spec.",
    "state.ability_damages",
    "storage.",
    "target_debuff.",
)


def _covered_files():
    """Every `.py` the covered roots hold, as paths under `src/calculator`."""
    return sorted(literal_defaults.targets(str(CALCULATOR / root) for root in ROOTS))


def _findings(name="damage.py"):
    return literal_defaults.scan([CALCULATOR / name])


def _covered_findings():
    """Every surviving site in the covered set, keyed the way `SURVIVORS` is."""
    return {
        (
            Path(finding.path).resolve().relative_to(CALCULATOR).as_posix(),
            finding.enclosing,
            finding.kind,
            finding.key,
        )
        for finding in literal_defaults.scan(_covered_files())
    }


def test_no_ability_payload_read_carries_a_literal_default():
    """Bucket A is zero: every payload field goes through ability_atoms."""
    offenders = [
        f"{finding.line}: {finding.expression}"
        for finding in _findings()
        if finding.expression.startswith(PAYLOAD_RECEIVERS)
    ]
    assert offenders == []


def test_the_surviving_literal_defaults_are_the_frozen_ones():
    """Nothing new joins a bucket, and a retired row leaves it."""
    found = _covered_findings()
    assert found - SURVIVORS == set()
    assert SURVIVORS - found == set()


def test_every_covered_root_exists():
    """A root renamed out from under the pin fails here, not silently."""
    missing = [root for root in ROOTS if not (CALCULATOR / root).exists()]
    assert missing == []


def test_the_covered_set_and_the_tail_partition_the_package():
    """The tail is explicit: a file joins the pin, it never drifts into it."""
    covered = {path.resolve() for path in _covered_files()}
    everything = {path.resolve() for path in CALCULATOR.rglob("*.py")}
    uncovered = {
        path.relative_to(CALCULATOR).as_posix() for path in everything - covered
    }
    assert covered <= everything
    assert uncovered == set(TAIL)


def test_the_scanner_still_finds_a_planted_cached_data_default(tmp_path):
    """The gate is driven by a real scan, not by an empty one."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def f(info):" + chr(10) + "    return info.get('dot_duration', 0.0)" + chr(10),
        encoding="utf-8",
    )
    assert [f.key for f in literal_defaults.scan([planted])] == ["'dot_duration'"]


def test_an_accumulator_index_and_a_none_coalesce_stay_exempt(tmp_path):
    """Both exemptions are shape rules, so a planted pair proves them."""
    planted = tmp_path / "exempt.py"
    planted.write_text(
        "def f(by_type, dtype, maybe):"
        + chr(10)
        + "    return by_type.get(dtype, 0.0), (maybe or 0.0)"
        + chr(10),
        encoding="utf-8",
    )
    assert literal_defaults.scan([planted]) == []
