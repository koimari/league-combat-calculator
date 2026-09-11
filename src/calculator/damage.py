"""The fight damage engine: the ordered list of steps one fight runs.

This module is champion-agnostic. Champion ability data (including cooldowns)
is provided by the caller via the ``ability_damages`` dict. Item effects are
delegated to ``item_effects``, and every step below lives in ``fight/``.

The on-hit authoring contract a champion module writes against sits on the step
that reads it: stack acceleration and ``on_hit`` in
``fight/autos/on_hit_layering.py``, ``empower_window`` in
``fight/autos/empower_windows.py``, ``applies_item_on_hits`` in
``fight/autos/on_hit_stream.py``, and ``stacking_dot`` with
``stack_triggered_buff`` in ``fight/rotation/stack_timeline.py``.
"""

# file-length-ok: the bulk is the import block naming every step and the one
# ordered call list that is this module's whole job; a step lifted out is a
# call whose place in the order lives in another file.
import math
from collections.abc import Iterable, Mapping
from typing import Any

from . import item_effects
from .fight.after.amplifiers import _add_expose_weakness, _apply_damage_amplifiers
from .fight.after.empowered_swings import _reattribute_empowered_swings
from .fight.after.execute_display import _add_execute_display
from .fight.after.fight_notes import _collect_fight_notes
from .fight.after.lethality_windows import _apply_temporary_lethality_windows
from .fight.after.reprice import _add_shadowflame_cinderbloom
from .fight.after.shield_outcome import _resolve_starting_shield_outcome
from .fight.after.stored_damage import _add_stored_damage
from .fight.autos.first_auto_strikes import (
    _add_first_auto_strikes,
    _author_energized_ability_procs,
)
from .fight.autos.on_hit_healing import _add_first_auto_healing, _add_on_hit_healing
from .fight.autos.on_hit_layering import _layer_on_hit_effects
from .fight.autos.on_hit_stream import _add_lifesteal_events, _add_omnivamp_events
from .fight.autos.simulation import _simulate_auto_attacks
from .fight.autos.spellblade import (
    _add_spellblade_damage,
    _prepare_spellblade_attack_schedule,
)
from .fight.autos.stacking_strikes import _add_stacking_strikes
from .fight.autos.swing_profile import _on_hit_effectiveness
from .fight.autos.swing_schedule import (
    _auto_attack_timestamps,
    _prepare_support_attack_schedule,
)
from .fight.config import FightConfig
from .fight.items.actives import _add_auto_cooldown_strikes, _add_item_active_damage
from .fight.items.burns import _add_burn_damage
from .fight.items.cast_procs import _add_item_proc_damage, _add_late_phase_proc_damage
from .fight.items.muramana import _add_per_ability_hit_damage
from .fight.items.secondary_delivery import (
    _add_bolt_delivery,
    _add_cleave_delivery,
    _add_cone_delivery,
)
from .fight.items.ultimate_procs import _add_ultimate_proc_damage
from .fight.ledger.breakdown import _is_auto_stream_key
from .fight.ledger.coverage import _resolve_timeline_coverage
from .fight.ledger.event_ledger import _ordered_damage_events
from .fight.ledger.execute_stamps import _stamp_execute_thresholds
from .fight.results import SwingStream
from .fight.rotation.ability_rotation import _compute_ability_rotation
from .fight.rotation.dot_ticks import (
    _add_stacking_dot_damage,
    _author_ability_dot_events,
)
from .fight.rotation.precomputed_procs import _add_precomputed_proc_damage
from .fight.rotation.shaped_charge import _add_shaped_charge_damage
from .fight.runes.keystone_attacks import (
    _add_keystone_fleet_footwork,
    _add_keystone_grasp_damage,
    _add_keystone_hail_of_blades,
    _add_keystone_lethal_tempo,
)
from .fight.runes.keystone_casts import (
    _add_keystone_aery_damage,
    _add_keystone_aftershock_damage,
)
from .fight.runes.keystone_ledger_walk import (
    _add_keystone_dark_harvest,
    _add_keystone_deathfire,
)
from .fight.runes.keystone_stacks import (
    _add_keystone_conqueror,
    _add_rune_proc_amp_damage,
    _add_rune_window_amp_damage,
)
from .fight.runes.page_damage import (
    _add_dedicated_keystone_receipts,
    _add_rune_ability_proc_damage,
    _add_rune_no_damage_receipts,
    _add_rune_proc_damage,
    _add_rune_receipts_applied_elsewhere,
)
from .fight.setup.combat_state import _resolve_combat_state
from .fight.setup.shield_reaver import _apply_shield_reaver_venom
from .fight.rotation.cast_resource_lockout import apply_lockout_attack_speed
from .fight.setup.stat_buff_ultimates import _apply_stat_buff_ultimates
from .fight.stacks.ashe import _add_ashe_focus
from .fight.stacks.aurelion_sol import _add_aurelion_sol_stardust
from .fight.stacks.bard import _add_bard_travelers_call
from .fight.stacks.heimerdinger import _add_heimerdinger_w_e
from .fight.stacks.ksante import _add_ksante_path_maker
from .fight.stacks.rengar import _add_rengar_ferocity
from .fight.stacks.senna import _add_senna_souls
from .fight.state import FightState
from .interpreters import on_hit_strike
from .ledger_inputs import ResultProjection, ShieldOutcomeInputs
from .ledger_projection import shield_outcome_projection


def shield_outcome_inputs(
    config: FightConfig, items: Iterable[dict[str, Any]]
) -> ShieldOutcomeInputs:
    """One fight's facts, as the shield outcome's readers are decided by."""
    return ShieldOutcomeInputs(
        item_names=tuple(item_effects.resolved_item_name(item) for item in items),
        target_threshold_health_heal=config.target_threshold_health_heal,
    )


def _require_target_class_support(
    config: FightConfig, items: list[dict[str, Any]]
) -> None:
    """Refuse a non-champion-class fight the item model cannot price.

    An item whose cached effect text names a target class it is not
    adjudicated for would be priced with the champion-class reading (Statikk
    Shiv's Electrospark is 60 magic damage on a champion and a sourced 90 on a
    non-champion), so the fight fails closed naming every offending clause."""
    denials = item_effects.target_class_denials(
        items,
        config.target_class,
        adjudicated_mechanics=on_hit_strike.adjudicated_target_class_mechanics,
    )
    if denials:
        raise ValueError(
            f"target_class={config.target_class!r} is not supported by this "
            "build: " + "; ".join(denials)
        )


def _swing_stream(state: FightState) -> SwingStream:
    """The auto stream every strike step reads, resolved once for all of them.

    The schedule is empty when it disagrees with the priced swing count, which
    is what keeps a row that cannot be timed coarse.
    """
    times = _auto_attack_timestamps(state)
    return SwingStream(
        times if len(times) == state.num_auto_attacks else [],
        _on_hit_effectiveness(state),
    )


def calculate_fight_damage(
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    config: FightConfig,
    *,
    score_only: bool = False,
    tuple_ledger: bool = False,
    item_options: Mapping[str, Mapping[str, int | float]] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate total damage dealt over a fight duration.

    In time-based mode, abilities recast when their cooldown expires within
    the fight duration. In one-rotation mode, each ability is cast exactly
    once (fight_duration still matters for burns/DoTs/procs).

    Ability haste is read from ``champion_stats`` (keys ``ability_haste``
    and ``basic_ability_haste``), like every other champion stat.

    Args:
        champion_stats: Calculated champion stats dictionary.  **The fight
            buffs it in place** (``_apply_stat_buff_ultimates``), which is
            what makes ``run_fight`` able to report fight-effective stats;
            ``run_fight`` therefore hands over a copy it owns. A direct
            caller that reuses one stats dict across fights instead sees
            the buffs compound — attack speed, and so the swing count and
            every row riding it, growing on every call.
        ability_damages: Parsed ability damage dictionary.
        items: List of item data for checking passives.
        config: The fight's :class:`FightConfig` (target, duration, mode).

    Returns:
        Dictionary with damage breakdown and total.
    """
    # ── Target class admission (P3-3M) ──────────────────────────────────
    _require_target_class_support(config, items)

    # ── Shield Reaver venom cuts the target's non-magic shields ─────────
    config, shield_reaver_notes = _apply_shield_reaver_venom(
        config, items, champion_stats
    )

    # ── Resolve resistances, penetration, amps, and attack timing ───────
    state = _resolve_combat_state(
        champion_stats,
        ability_damages,
        items,
        config,
        item_options=item_options,
        champion_options=champion_options,
    )
    state.score_only = score_only
    state.notes.extend(shield_reaver_notes)

    # ── Stat buffs from abilities (e.g. Aatrox R bonus AD) ─────────────
    _apply_stat_buff_ultimates(state)
    _prepare_support_attack_schedule(state)

    # ── Ability rotation, precomputed procs, DoTs, and Shaped Charge ────
    rotation = _compute_ability_rotation(state)
    # The plan is what decides how often a self-silencing bar filled, so the
    # grant those windows buy is rated here, once the plan exists and before
    # the swing stream is counted.
    apply_lockout_attack_speed(state)
    state.ability_cast_times = tuple(
        (str(event["slot"]), float(event["time"])) for event in rotation.cast_events
    )
    _add_rengar_ferocity(state, rotation)
    _author_ability_dot_events(state, rotation)
    _add_precomputed_proc_damage(state, rotation)
    _add_stacking_dot_damage(state)
    _add_shaped_charge_damage(state, rotation)

    # ── Auto attacks (per-auto crit simulation) ─────────────────────────
    _prepare_spellblade_attack_schedule(state, rotation)
    autos = _simulate_auto_attacks(state)

    # ── On-hit damage layered onto the autos ────────────────────────────
    on_hits = _layer_on_hit_effects(state, autos, rotation)

    # ── Spellblade + Dusk and Dawn double on-hit ────────────────────────
    spellblade = _add_spellblade_damage(state, rotation, autos, on_hits)

    # ── Burn / DoT item damage ──────────────────────────────────────────
    _add_burn_damage(state, rotation)

    # ── Item procs, then the zone an ultimate opens (Malignance) ────────
    _add_item_proc_damage(state, rotation)
    _add_ultimate_proc_damage(state, rotation)

    # ── Rune procs (Electrocute-class stack triggers) ────────────────
    _add_rune_proc_damage(state, rotation)

    # ── Rune ability-cast procs (Arcane Comet-class) ───────────────────
    _add_rune_ability_proc_damage(state, rotation)

    # ── Keystone threshold proc (Dark Harvest-class) ────────────────────
    _add_keystone_dark_harvest(state, rotation)

    # ── Runes that book no damage, and their receipts ───────────────────
    _add_rune_no_damage_receipts(state)
    _add_rune_receipts_applied_elsewhere(state)
    _add_dedicated_keystone_receipts(state)

    _add_item_active_damage(state, rotation)

    # ── The strikes that proc once or on a counter, and what they deliver
    #    at a second subject ─────────────────────────────────────────────
    swings = _swing_stream(state)
    energized_by_ability = _author_energized_ability_procs(
        state, rotation, swings=swings
    )
    _add_bolt_delivery(state, on_hits, swings=swings)
    _add_cleave_delivery(state, swings=swings)
    _add_first_auto_strikes(
        state,
        rotation,
        on_hits,
        spellblade=spellblade,
        ability_consumed_items=energized_by_ability,
        swings=swings,
    )
    empowered_autos = _add_auto_cooldown_strikes(state, swings=swings)
    _add_cone_delivery(state, empowered_autos=empowered_autos, swings=swings)
    _add_stacking_strikes(
        state, rotation, autos, on_hits, spellblade=spellblade, swings=swings
    )
    _add_late_phase_proc_damage(state, rotation)
    _add_per_ability_hit_damage(state, rotation)

    # ── Shadowflame and Expose Weakness ─────────────────────────────────
    _add_on_hit_healing(state, autos, on_hits)
    _add_first_auto_healing(state)
    _add_shadowflame_cinderbloom(state, config, rotation)
    _add_expose_weakness(state, rotation, spellblade)

    # ── Deathfire's typed refreshed burn ────────────────────────────────
    _add_keystone_deathfire(state, rotation)

    # ── Conqueror's certified stack state and max-stack healing ────────
    _add_keystone_conqueror(state, rotation)

    # ── Summon Aery damage and signal cadence ───────────────────────────
    _add_keystone_aery_damage(state, rotation)

    # ── Aftershock delayed shockwave from immobilizing casts ────────────
    _add_keystone_aftershock_damage(state, rotation)

    # ── Grasp's timed combat stacks and empowered basic attack ──────────
    _add_keystone_grasp_damage(state, rotation)

    # ── Hail of Blades' temporary attack window and true-damage rider ───
    _add_keystone_hail_of_blades(state, rotation)

    # ── Lethal Tempo's stacked attack window and max-stack bolt ────────
    _add_keystone_lethal_tempo(state, rotation)

    # ── Fleet Footwork's charged heal and movement window ──────────────
    _add_keystone_fleet_footwork(state, rotation)

    # ── Rune opening-window bonus (First Strike-class) ────────────────
    _add_rune_window_amp_damage(state, rotation)

    # ── Rune stacked proc plus lasting amp (Press the Attack-class) ───
    _add_rune_proc_amp_damage(state, rotation)

    # ── Fight-wide damage amplifiers ────────────────────────────────────
    _apply_damage_amplifiers(state, rotation)

    # ── Empowered-auto swings shown on the ability that forced them ─────
    _reattribute_empowered_swings(state, rotation.cast_events)

    # ── Temporary penetration windows (Voltaic Firmament) ──────────────
    # Resolve after every source and amplifier has authored its events, but
    # before reconstructing the shared ledger consumed by shields/healing.
    _apply_temporary_lethality_windows(state)
    _add_stored_damage(state, rotation)

    # ── Execute threshold display (The Collector) ───────────────────────
    _add_execute_display(state)

    # ── Notes for conditional item assumptions ──────────────────────────
    _collect_fight_notes(state, rotation, on_hits)

    # The exact event ledger the shield/temporary-health resolver consumes is
    # also the fight's returned ``damage_events``: nothing mutates the
    # breakdown after this point, so reconstruct it once.  Downstream team
    # simulation uses this same ordered ledger; it must never reconstruct
    # timing from aggregate breakdown rows.
    # ``tuple_ledger`` callers (the scoring fast path, for champions with
    # no self-heal rules and no Protoplasm target) consume the ledger as
    # light rows directly; every other caller gets the dict contract.
    damage_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.ledger_target_index,
        light=tuple_ledger,
        lean=score_only,
    )
    # ── Generic life-steal packets from exact physical attack events ─────
    # Run after the shared ledger is reconstructed so forced/basic attacks
    # carried by ability rows retain their explicit basic_attack marker.
    if not tuple_ledger:
        _add_lifesteal_events(state, damage_events)
        _add_omnivamp_events(state, damage_events)
        # ── Execute thresholds stamped onto the rows they terminate ─────
        _stamp_execute_thresholds(state, damage_events)
    if (
        score_only
        and shield_outcome_projection(shield_outcome_inputs(config, items))
        is ResultProjection.SKIPPED_SHIELD_OUTCOME
    ):
        # Score-mode consumers replay shields inside the coupled survival
        # walk and never read the one-pair shield outcome.  The two readers
        # that keep it are declared conditions rather than clauses spelled
        # here: the Protoplasm coverage downgrade below, which reads the
        # target's threshold heal — the same condition the pipeline's ledger
        # gate reads, answered by one function at both — and the holders
        # whose ``takedown_events`` synthesis reads ``target_ending_health``
        # off this outcome.
        shield_outcome: dict[str, float] = {}
    else:
        shield_outcome = _resolve_starting_shield_outcome(state, config, damage_events)
    _add_senna_souls(state, rotation, shield_outcome, damage_events)
    _add_aurelion_sol_stardust(state, rotation)
    _add_bard_travelers_call(state, rotation)
    _add_heimerdinger_w_e(state, rotation)
    _add_ksante_path_maker(state, rotation)
    _add_ashe_focus(state, rotation)
    timeline_coverage = _resolve_timeline_coverage(
        state,
        items,
        damage_events,
        rotation.control_events,
        shield_outcome,
        threshold_health_heal=config.target_threshold_health_heal,
        score_only=score_only,
    )
    if state.clip_to_window:
        state.notes.append(
            "Damage timed past the fight's end is not counted "
            "(count_damage_after_fight_end is off)."
        )
    return {
        "breakdown": state.breakdown,
        "total_damage": state.total_damage,
        "effective_mr": state.resists.effective_mr,
        "effective_armor": state.resists.effective_armor,
        # The selected keystone, whichever engine priced it: its own
        # ``_add_keystone_*`` model or the compiled rune page.
        "keystone": config.keystone,
        "notes": state.notes,
        "cast_timeline": rotation.cast_events,
        "resource_spent": rotation.resource_spent,
        "resource_remaining": rotation.resource_remaining,
        "resource_ledger": rotation.resource_ledger,
        "resource_restore_events": [
            {
                "time": round(float(time), 6),
                "amount": round(float(amount), 6),
                "source": "Catalyst of Aeons (Eternity)",
            }
            for time, amount in state.resource_restore_events
            if math.isfinite(float(time)) and math.isfinite(float(amount))
        ],
        "timeline_coverage": timeline_coverage,
        "damage_events": damage_events,
        "control_events": rotation.control_events,
        **shield_outcome,
        # Exposed for champion-specific ability calculators (Case 1: stack
        # acceleration). Champions like Vayne can check which autos grant
        # double stacks to calculate ability procs more accurately.
        "phantom_hit_autos": on_hits.phantom_hit_autos,
        "phantom_hit_count": on_hits.phantom_hit_count,
        "item_state_receipts": item_effects.item_state_receipts(
            items,
            item_options,
            fight_duration_seconds=config.fight_duration_seconds,
            is_melee=state.is_melee,
            bonus_health=float(champion_stats["bonus_health"]),
            bonus_mana=float(champion_stats["bonus_mana"]),
            max_mana=float(champion_stats["max_mana"]),
            total_attack_damage=float(champion_stats["attack_damage"]),
            total_move_speed=float(champion_stats["move_speed"]),
            lethality=float(champion_stats["lethality"]),
        ),
    }


def split_auto_vs_ability(
    breakdown: Mapping[str, dict[str, Any]],
) -> tuple[float, float]:
    """Split a fight breakdown into (auto_attack_damage, ability_damage).

    Attribution rules, keyed off the breakdown key names the `fight/` steps emit:

    - Entries marked ``informational`` are display-only — their damage is
      zero or already counted in other rows (the engine marks its amp
      summaries, the execute-threshold row, and the Sundered Sky row
      this way) — so they are skipped.
    - Rows that declare ``auto_attack_fraction`` know their own
      composition (First Strike's window bonus spans both streams) and
      are split by it.
    - ``_is_auto_stream_key`` rows count as auto-attack damage.
    - ``damage_amp_<source>`` rows amplify both buckets, so their damage
      is redistributed proportionally to the pre-amp auto/ability ratio
      (dropped entirely if that total is zero).
    - Everything else counts as ability damage.
    """
    auto_attack_damage = 0.0
    ability_damage = 0.0
    redistributed_damage = 0.0  # damage_amp_<source> rows

    for key, entry in breakdown.items():
        dmg = entry.get("total_damage", 0.0)
        if entry.get("informational"):
            continue
        if "auto_attack_fraction" in entry:
            fraction = float(entry["auto_attack_fraction"])
            auto_attack_damage += dmg * fraction
            ability_damage += dmg * (1.0 - fraction)
        elif _is_auto_stream_key(key):
            auto_attack_damage += dmg
        elif key.startswith("damage_amp_"):
            # Amplifiers scale both buckets — redistribute proportionally
            # below instead of attributing to either bucket.
            redistributed_damage += dmg
        else:
            ability_damage += dmg

    # Damage amplification — split proportionally.
    pre_amp_total = auto_attack_damage + ability_damage
    if pre_amp_total > 0:
        auto_ratio = auto_attack_damage / pre_amp_total
        auto_attack_damage += redistributed_damage * auto_ratio
        ability_damage += redistributed_damage * (1 - auto_ratio)

    return auto_attack_damage, ability_damage


def split_by_damage_type(
    breakdown: Mapping[str, dict[str, Any]],
) -> dict[str, float]:
    """Split a fight breakdown into physical/magic/true damage totals.

    Attribution rules, keyed off the row fields the `fight/` steps emit:

    - Entries marked ``informational`` are display-only — their damage
      is zero or already counted in other rows — so they are skipped.
    - Entries carrying ``damage_by_type`` (mixed rows built from typed
      parts) contribute their exact per-type composition.
    - Entries with a singular ``damage_type`` contribute their full
      damage to that bucket.
    - Everything else — ``damage_amp_<source>`` rows and mixed rows
      whose composition is not reconstructable — scales or combines all
      types, so its damage is redistributed proportionally to the typed
      totals (dropped entirely if that total is zero).
    """
    totals = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    redistributed_damage = 0.0

    for entry in breakdown.values():
        if entry.get("informational"):
            continue
        by_type = entry.get("damage_by_type")
        if by_type is not None:
            # Keys are validated DamagePart/DamageType values
            # (physical/magic/true); a stray key should raise.
            for dtype, amount in by_type.items():
                totals[dtype] += amount
        elif entry.get("damage_type") in totals:
            totals[entry["damage_type"]] += entry.get("total_damage", 0.0)
        else:
            redistributed_damage += entry.get("total_damage", 0.0)

    typed_total = sum(totals.values())
    if typed_total > 0:
        for dtype, typed in totals.items():
            totals[dtype] = typed + redistributed_damage * (typed / typed_total)

    return totals
