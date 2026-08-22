"""Rule-5 lint: the scanned files read no cached data behind a literal default.

`scripts/literal_defaults.py` flags `.get("key", <literal>)`, `<get> or
<literal>` and `getattr(o, "attr", <literal>)`, exempting an index into a
local accumulator and a None-coalesce by shape.  What survives is frozen here
per file by enclosing function and key — never by line number, so an edit
above a site does not turn this red.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402  (path set above)

import literal_defaults  # noqa: E402  (path set above)

CALCULATOR = Path(__file__).resolve().parent.parent / "src" / "calculator"

#: Reads off an internal breakdown or damage-event row.  These rows have no
#: schema home the way `_damage_event_row`'s mandatory five do; one row
#: dataclass retires the whole list at once (campaign decision D3, bucket D1).
ROW_READS = frozenset(
    {
        ("_ability_dot_tick_events", "dict.get", '"casts"'),
        ("_ability_dot_tick_events", "dict.get", '"total_damage"'),
        ("_add_ashe_focus", "dict.get", '"slot"'),
        ("_add_ashe_focus", "or-default", '"auto_attacks"'),
        ("_add_ashe_focus", "or-default", '"damage_events"'),
        ("_add_aurelion_sol_stardust", "dict.get", '"ordinal"'),
        ("_add_aurelion_sol_stardust", "dict.get", '"slot"'),
        ("_add_aurelion_sol_stardust", "dict.get", '"time"'),
        ("_add_aurelion_sol_stardust", "or-default", '"ordinal"'),
        ("_add_copied_stacking_on_hit_packets", "dict.get", '"packets"'),
        ("_add_copied_stacking_on_hit_packets", "dict.get", '"time"'),
        ("_add_heimerdinger_w_e", "dict.get", '"raw_damage"'),
        ("_add_keystone_conqueror", "dict.get", '"reason"'),
        ("_add_keystone_conqueror", "dict.get", '"sequence"'),
        ("_add_keystone_dark_harvest", "dict.get", '"time"'),
        ("_add_keystone_deathfire", "dict.get", '"event_precision"'),
        ("_add_rengar_ferocity", "dict.get", '"detail"'),
        ("_add_rengar_ferocity", "dict.get", '"ordinal"'),
        ("_add_rengar_ferocity", "dict.get", '"reason"'),
        ("_add_rengar_ferocity", "dict.get", '"slot"'),
        ("_add_rengar_ferocity", "or-default", '"ordinal"'),
        ("_add_senna_souls", "dict.get", '"target"'),
        ("_add_single_proc_on_hits", "dict.get", '"event_precision"'),
        ("_add_spellblade_damage", "dict.get", '"casts"'),
        ("_add_stored_damage", "dict.get", '"casts"'),
        ("_add_stored_damage", "dict.get", '"slot"'),
        ("_add_stored_damage", "dict.get", '"time"'),
        ("_apply_command_amp", "or-default", '"damage_events"'),
        ("_apply_damage_amplifiers", "dict.get", '"total_damage"'),
        ("_apply_mana_resource_limits", "dict.get", '"burst_seconds"'),
        ("_apply_mana_resource_limits", "dict.get", '"window_seconds"'),
        ("_apply_temporary_lethality_windows", "dict.get", '"event_phase"'),
        ("_apply_temporary_lethality_windows", "dict.get", '"total_damage"'),
        ("_author_ability_dot_events", "dict.get", '"slot"'),
        ("_author_empowered_swing_events", "dict.get", '"damage"'),
        ("_author_empowered_swing_events", "dict.get", '"damage_type"'),
        ("_author_empowered_swing_events", "dict.get", '"total_damage"'),
        ("_conqueror_trigger_events", "dict.get", '"phase"'),
        ("_conqueror_trigger_events", "dict.get", '"slot"'),
        ("_conqueror_trigger_events", "dict.get", '"time"'),
        ("_damaging_cast_times", "dict.get", '"total_raw"'),
        ("_dark_harvest_trigger_event", "dict.get", '"phase"'),
        ("_deathfire_trigger_events", "dict.get", '"event_precision"'),
        ("_deathfire_trigger_events", "dict.get", '"slot"'),
        ("_deathfire_trigger_events", "dict.get", '"time"'),
        ("_empowered_swing_consumers", "dict.get", '"casts"'),
        ("_empowered_swing_consumers", "dict.get", '"slot"'),
        ("_event_timeline_coverage", "dict.get", '"casts"'),
        ("_event_timeline_coverage", "dict.get", '"event_precision"'),
        ("_event_timeline_coverage", "dict.get", '"total_damage"'),
        ("_feed_ashe_focus_stack", "dict.get", '"time"'),
        ("_feed_ashe_focus_stack", "or-default", '"time"'),
        ("_first_damaging_ability_event", "dict.get", '"event_precision"'),
        ("_first_damaging_ability_event", "dict.get", '"total_damage"'),
        ("_first_damaging_ability_event", "or-default", '"total_damage"'),
        ("_hypershot_delta_events", "dict.get", '"damage_type"'),
        ("_hypershot_delta_events", "dict.get", '"total_damage"'),
        ("_impaired_instance_times", "dict.get", '"total_raw"'),
        ("_item_proc_precision", "dict.get", '"casts"'),
        ("_item_proc_precision", "or-default", '"casts"'),
        ("_layer_on_hit_effects", "dict.get", '"casts"'),
        ("_muramana_cast_receipt", "dict.get", '"total_damage"'),
        ("_muramana_cast_receipt", "or-default", '"total_damage"'),
        ("_ordered_damage_events", "dict.get", '"casts"'),
        ("_ordered_damage_events", "dict.get", '"count"'),
        ("_ordered_damage_events", "dict.get", '"slot"'),
        ("_ordered_damage_events", "dict.get", '"time"'),
        ("_ordered_damage_events", "dict.get", '"total_damage"'),
        ("_ordered_damage_events", "dict.get", '"total_raw"'),
        ("_ordered_damage_events", "or-default", '"total_raw"'),
        ("_reattribute_empowered_swings", "dict.get", '"casts"'),
        ("_reattribute_empowered_swings", "dict.get", '"count"'),
        ("_reattribute_empowered_swings", "dict.get", '"damage_per_hit"'),
        ("_resolve_starting_shield_outcome", "dict.get", '"execute_threshold_ratio"'),
        ("_resolve_starting_shield_outcome", "dict.get", '"raw_damage"'),
        ("_resolve_starting_shield_outcome", "dict.get", '"total_damage"'),
        ("_resolve_starting_shield_outcome", "or-default", '"execute_threshold_ratio"'),
        ("_resolve_starting_shield_outcome", "or-default", '"raw_damage"'),
        ("_resource_ledger_public", "dict.get", '"bonus_delta"'),
        ("_resource_ledger_public", "or-default", '"bonus_delta"'),
        ("_return_denied_burst_budget", "dict.get", '"burst_seconds"'),
        ("_row_damage_parts", "dict.get", '"total_damage"'),
        ("_schedule_enlighten", "dict.get", '"tick"'),
        ("_self_shield_times", "dict.get", '"time"'),
        ("_shaped_charge_proc_receipts", "dict.get", '"event_precision"'),
        ("_slot_ordinals", "dict.get", '"ordinal"'),
        ("_slot_ordinals", "dict.get", '"slot"'),
        ("_slot_ordinals", "or-default", '"ordinal"'),
        ("_stacked_champion_proc_times", "dict.get", '"event_precision"'),
        ("_stacked_champion_proc_times", "dict.get", '"total_damage"'),
        ("add", "dict.get", '"cc_duration"'),
        ("add", "or-default", '"cc_duration"'),
        ("emit_until", "dict.get", '"category"'),
        ("emit_until", "dict.get", '"source"'),
        ("split_auto_vs_ability", "dict.get", '"total_damage"'),
        ("split_by_damage_type", "dict.get", '"total_damage"'),
    }
)

#: Request-supplied per-item state, not cached data: an absent key is the
#: item's declared off state, and `ITEM_INPUT_OPTIONS` owns what that is.
REQUEST_ITEM_STATE = frozenset(
    {
        ("actualizer_active_seconds", "dict.get", '"mana_made_real_active"'),
        ("actualizer_active_seconds", "dict.get", '"mana_made_real_active_seconds"'),
        ("actualizer_active_seconds", "or-default", '"mana_made_real_active"'),
        ("input_option_crit_chance", "dict.get", '"crit_stacks"'),
        ("input_option_retribution_bonus_ad", "dict.get", '"missing_health_percent"'),
        ("item_state_receipts", "dict.get", '"Endless Hunger"'),
        ("item_state_receipts", "dict.get", '"Heartsteel"'),
        ("item_state_receipts", "dict.get", '"Hubris"'),
        ("item_state_receipts", "dict.get", '"Knight\'s Vow"'),
        ("item_state_receipts", "dict.get", '"Rod of Ages"'),
        ("item_state_receipts", "dict.get", '"Tear of the Goddess"'),
        ("item_state_receipts", "dict.get", '"Yun Tal Wildarrows"'),
        ("item_state_receipts", "dict.get", '"bonus_health"'),
        ("item_state_receipts", "dict.get", '"crit_stacks"'),
        ("item_state_receipts", "dict.get", '"eminence_active_seconds"'),
        ("item_state_receipts", "dict.get", '"eminence_stacks"'),
        ("item_state_receipts", "dict.get", '"feast_active_seconds"'),
        ("item_state_receipts", "dict.get", '"holder_above_30_percent"'),
        ("item_state_receipts", "dict.get", '"manaflow_bonus_mana"'),
        ("item_state_receipts", "dict.get", '"missing_health_percent"'),
        ("item_state_receipts", "dict.get", '"shared_riches_gold"'),
        ("item_state_receipts", "dict.get", '"timeless_stacks"'),
        ("item_state_receipts", "dict.get", '"ward_uses"'),
        ("item_state_receipts", "dict.get", '"worthy_target_index"'),
        ("item_state_receipts", "dict.get", '"worthy_within_range"'),
        ("item_state_receipts", "or-default", '"Overlord\'s Bloodmail"'),
        ("item_state_receipts", "or-default", '"crit_stacks"'),
        ("item_state_receipts", "or-default", '"eminence_active_seconds"'),
        ("item_state_receipts", "or-default", '"eminence_stacks"'),
        ("item_state_receipts", "or-default", '"feast_active_seconds"'),
        ("item_state_receipts", "or-default", '"shared_riches_gold"'),
        ("item_state_receipts", "or-default", '"ward_uses"'),
    }
)

#: Reads on the in-module `ITEM_INPUT_OPTIONS` declaration itself.  An absent
#: facet means this option declares none, which is a source fact, not a
#: cached-data miss.
OPTION_SCHEMA = frozenset(
    {
        ("_input_option_stat_bonuses", "dict.get", '"bonus_ap_per_unit"'),
        ("_input_option_stat_bonuses", "dict.get", '"bonus_health_per_unit"'),
        ("_input_option_stat_bonuses", "dict.get", '"bonus_mana_per_unit"'),
        ("_item_option_schemas", "dict.get", '"options"'),
        ("input_option_float_value", "dict.get", '"step"'),
        ("input_option_float_value", "or-default", '"step"'),
        ("validate_item_input_options", "dict.get", '"step"'),
        ("validate_item_input_options", "or-default", '"step"'),
    }
)

#: A loadout row's own name.  The empty string is a sentinel the next
#: statement rejects or skips past; no number rides on it.
LOADOUT_NAMES = frozenset(
    {
        ("_cached_sustain_stat", "or-default", '"name"'),
        ("_resolve_damage_effects_uncached", "dict.get", '"name"'),
        ("active_secondary_ad_item_name", "dict.get", '"name"'),
        ("cleave_on_hit_item_name", "dict.get", '"name"'),
        ("grouped_sustain_stat_percent", "or-default", '"name"'),
        ("hydra_secondary_item_name", "dict.get", '"name"'),
        ("resolve_damage_effects", "dict.get", '"name"'),
        ("target_class_denials", "dict.get", '"name"'),
        ("target_class_denials", "or-default", '"name"'),
    }
)

#: Atom rows compared against the registry.  The empty tuple is the failure
#: branch: each of these raises on the next line rather than using it.
ATOM_ROWS = frozenset(
    {
        ("counter_trigger", "dict.get", '"counter_trigger"'),
        ("dorans_helm_helping_hand_minion_damage", "dict.get", '"values"'),
        ("guardian_angel_rebirth_declaration", "dict.get", '"values"'),
        ("ionian_insight_summoner_spell_haste", "dict.get", '"values"'),
        ("spell_shield_cooldown_seconds", "dict.get", '"values"'),
    }
)

#: Strict traversals of a raw cached ability row.  Every one of these feeds a
#: shape check whose failure branch raises, naming champion, slot and source —
#: the empty default is the path *to* that raise, never a served value.
WIKI_TRAVERSALS = frozenset(
    {
        ("_valid_atom_hash", "dict.get", '"hash"'),
        ("ranked_ability_atom_value", "dict.get", '"values"'),
        ("required_ability_atom", "dict.get", '"evidence"'),
        ("required_ranked_attribute_atom", "dict.get", '"abilities"'),
        ("required_ranked_attribute_atom", "dict.get", '"attribute"'),
        ("required_ranked_attribute_atom", "dict.get", '"effects"'),
        ("required_ranked_attribute_atom", "dict.get", '"leveling"'),
        ("required_ranked_attribute_atom", "dict.get", '"modifiers"'),
    }
)

#: Every scanned file and the survivors frozen for it.  A file joins this map
#: only once it is clean — that is what "widen one file at a time" means.
SCANNED = {
    "damage.py": ROW_READS,
    "item_effects.py": REQUEST_ITEM_STATE | OPTION_SCHEMA | LOADOUT_NAMES | ATOM_ROWS,
    "ability_atoms.py": WIKI_TRAVERSALS,
}

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


def _findings(name="damage.py"):
    return literal_defaults.scan([CALCULATOR / name])


def test_no_ability_payload_read_carries_a_literal_default():
    """Bucket A is zero: every payload field goes through ability_atoms."""
    offenders = [
        f"{finding.line}: {finding.expression}"
        for finding in _findings()
        if finding.expression.startswith(PAYLOAD_RECEIVERS)
    ]
    assert offenders == []


@pytest.mark.parametrize("name", sorted(SCANNED))
def test_the_surviving_literal_defaults_are_the_frozen_ones(name):
    """Nothing new joins a file's list, and a retired row leaves it."""
    found = {(f.enclosing, f.kind, f.key) for f in _findings(name)}
    assert found - SCANNED[name] == set()
    assert SCANNED[name] - found == set()


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
