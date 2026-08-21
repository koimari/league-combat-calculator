"""Rule-5 lint: damage.py reads no cached data behind a literal default.

`scripts/literal_defaults.py` flags `.get("key", <literal>)`, `<get> or
<literal>` and `getattr(o, "attr", <literal>)`, exempting an index into a
local accumulator and a None-coalesce by shape.  What survives is frozen here
by enclosing function and key — never by line number, so an edit above a site
does not turn this red.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import literal_defaults  # noqa: E402  (path set above)

ENGINE = Path(__file__).resolve().parent.parent / "src" / "calculator" / "damage.py"

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

#: Spelled with getattr against rule 5 on purpose, and only here: as plain
#: attributes these two become visible to `scripts/term_census.py`, whose
#: Amendment R gates then require a coupled scenario arming Guardian's Horn
#: and a re-captured golden baseline.  Both fields are declared on FightState,
#: so neither default is reachable.
CENSUS_GETATTR = frozenset(
    {
        (
            "_apply_target_champion_damage_reduction",
            "getattr",
            '"target_champion_damage_flat_reduction"',
        ),
        (
            "_apply_target_champion_damage_reduction",
            "getattr",
            '"target_champion_dot_damage_flat_reduction"',
        ),
    }
)

ALLOWED = ROW_READS | CENSUS_GETATTR

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


def _findings():
    return literal_defaults.scan([ENGINE])


def test_no_ability_payload_read_carries_a_literal_default():
    """Bucket A is zero: every payload field goes through ability_atoms."""
    offenders = [
        f"{finding.line}: {finding.expression}"
        for finding in _findings()
        if finding.expression.startswith(PAYLOAD_RECEIVERS)
    ]
    assert offenders == []


def test_the_surviving_literal_defaults_are_the_frozen_ones():
    """Nothing new joins the list, and a retired row leaves it."""
    found = {(f.enclosing, f.kind, f.key) for f in _findings()}
    assert found - ALLOWED == set()
    assert ALLOWED - found == set()


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
