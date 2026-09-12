"""An ability's stat grant, and everything re-resolved from a buffed stat."""

import math
from collections.abc import Mapping

from ... import item_effects
from ...ability_atoms import ability_field, ability_sub_payload
from ...interpreters import rearmed_swings
from ...stats import calculate_attack_speed, resolve_move_speed
from ..cast_slots import _slot_is_cast, slot_cast_start
from ..config import BASE_CRIT_MULTIPLIER
from ..state import FightState, _crit_profile


def _kit_swing_ramp(state: FightState) -> rearmed_swings.DecayingStackRamp | None:
    """The ramp a CHAMPION declares over its own swing stream, or ``None``.

    Jax's Relentless Assault and its siblings are the record an item ramp
    already is: a bonus per stack, a cap, and how long a stack lives, with
    one stack landing per completed attack. The module states all three
    from its cache; nothing here knows which champion.
    """
    found = [
        (str(info.get("name", key)), info["swing_ramp"])
        for key, info in state.ability_damages.items()
        if isinstance(info, Mapping) and info.get("swing_ramp")
    ]
    if not found:
        return None
    if len(found) > 1:
        raise ValueError(
            "Two slots declare a swing_ramp ("
            + ", ".join(name for name, _ in found)
            + "); one swing stream carries one kit ramp"
        )
    owner, payload = found[0]
    for field in ("per_stack", "max_stacks", "stack_duration"):
        if payload.get(field) is None:
            raise ValueError(
                f"{owner}: swing_ramp declares no {field!r}; every number of "
                "the ramp is sourced by the module"
            )
    # ``first_stack`` is optional because most ramps price every stack alike;
    # a source that prices the first one apart (Jinx) states it, and absent
    # means absent rather than a stand-in number.
    first_stack = payload.get("first_stack")
    return rearmed_swings.DecayingStackRamp(
        per_stack=float(payload["per_stack"]),
        max_stacks=int(payload["max_stacks"]),
        stack_duration=float(payload["stack_duration"]),
        first_stack=None if first_stack is None else float(first_stack),
    )


def _swing_schedule_for(
    state: FightState,
) -> tuple[
    rearmed_swings.SwingSchedule | None, rearmed_swings.DecayingStackRamp | None
]:
    """The schedule walking this fight's swings, and the kit ramp beside it.

    A build's item ramp and a kit's own ramp re-rate ONE stream and both
    are real, so the walker takes both and adds their bonuses. A kit with
    no item ramp still needs a schedule to walk, so its own ramp becomes
    one; an item ramp keeps its window either way.
    """
    build = state.declared.charged_strikes.swing_schedule
    kit = _kit_swing_ramp(state)
    if kit is None:
        return build, None
    if build is None:
        return (
            rearmed_swings.SwingSchedule(
                ramp=None, window=None, schedules_single_rotation=False
            ),
            kit,
        )
    return build, kit


def _rate_attack_speed_grant(
    state: FightState, key: str, bonus_as_pct: float, window_seconds: float | None
) -> None:
    """Rate the swing stream at a kit's bonus attack speed and recount it.

    A grant with no window covers the fight; one with a window (Tristana Q,
    Kennen E, Xayah W) is placed from the first cast of the row *key* that
    grants it, and the autos ride the base rate before it, the buffed rate
    inside ``[cast_start, cast_start + window)`` and the base rate again
    after (the end-exclusive boundary).  The state holds one window, so a
    second windowed grant on the same kit raises rather than overwriting
    the first.  The build's own ramp (Rageblade's stacks) keeps walking
    through either grant: its swings are authored here for the autos step
    to read.  A flat stream is counted per phase, the floor convention the
    fight end uses.
    """
    base_as = state.attack_speed
    state.attack_speed = calculate_attack_speed(
        base_as, state.attack_speed_ratio, bonus_as_pct
    )
    active_window = None
    if window_seconds is not None:
        if state.as_window_slot:
            raise ValueError(
                f"{key} places a second attack-speed window; the fight holds "
                f"one, already placed by {state.as_window_slot}"
            )
        cast_start = slot_cast_start(state, key)
        state.as_window_slot = key
        state.as_window_start = cast_start
        state.as_window_end = cast_start + window_seconds
        state.as_window_base_rate = base_as
        active_window = rearmed_swings.ActiveWindow(
            cast_start, state.as_window_end, bonus_as_pct
        )
    ramp, kit_ramp = _swing_schedule_for(state)
    if ramp is not None and (
        kit_ramp is not None or ramp.schedules(one_rotation=state.one_rotation)
    ):
        times = rearmed_swings.swing_times(
            ramp,
            attack_speed=base_as if active_window is not None else state.attack_speed,
            attack_speed_ratio=state.attack_speed_ratio,
            duration_seconds=state.fight_duration_seconds,
            uptime=state.auto_attack_uptime,
            critical_chance=state.champion_stats["critical_strike_chance"] / 100.0,
            active_window=active_window,
            kit_ramp=kit_ramp,
        )
        state.support_attack_times = times
        state.num_auto_attacks = len(times)
        if active_window is not None:
            state.as_window_pre_autos = sum(t < active_window.start for t in times)
            state.as_window_autos = sum(
                active_window.start <= t < active_window.end for t in times
            )
        return
    uptime = state.auto_attack_uptime
    if active_window is None:
        state.num_auto_attacks = math.floor(
            state.attack_speed * state.fight_duration_seconds * uptime
        )
        return
    in_window = min(
        window_seconds, max(0.0, state.fight_duration_seconds - active_window.start)
    )
    state.as_window_pre_autos = math.floor(active_window.start * base_as * uptime)
    state.as_window_autos = math.floor(state.attack_speed * in_window * uptime)
    post_autos = math.floor(
        base_as * max(0.0, state.fight_duration_seconds - active_window.end) * uptime
    )
    state.num_auto_attacks = (
        state.as_window_pre_autos + state.as_window_autos + post_autos
    )


def _apply_stat_buff_ultimates(state: FightState) -> None:
    """Apply ability stat buffs (e.g. Aatrox R bonus AD) and resolve crit.

    Mutates ``champion_stats`` in place (callers observe the buffed stats,
    as before this refactor) and re-resolves anything derived from a
    buffed stat: attack damage, magic/armor penetration, and attack speed
    (which changes the fight's auto-attack count — note the Fiendhunter
    empowered/normal split is NOT recomputed here, matching the original
    behavior). Crit chance/multiplier are resolved afterwards so ability
    crit scaling and the auto-attack simulation both see buffed values.
    """
    stats = state.champion_stats
    resists = state.resists
    withheld: list[str] = []

    for key, ability_info in state.ability_damages.items():
        stat_buff = ability_info.get("stat_buff")
        if not stat_buff:
            continue
        if ability_info.get("cast_resource_lockout"):
            # This grant is worth its percent only inside the windows the
            # cast plan earns, and the plan does not exist yet.
            # ``cast_resource_lockout.apply_lockout_attack_speed`` rates it
            # once the rotation has run.
            continue
        if not _slot_is_cast(
            key, ability_info, state.cast_order, state.auto_attacks_only
        ):
            # An active's grant rides its cast: a rotation that never casts
            # the ability earns none of it, and autos-only casts nothing at
            # all. A passive's grant is always on.
            if state.auto_attacks_only:
                withheld.append(str(ability_info.get("name", key)))
            continue
        for stat_key, buff_value in stat_buff.items():
            stats[stat_key] = stats.get(stat_key, 0.0) + buff_value
        # Recalculate attack_damage if either AD component was buffed
        # (base AD buffs exist too: Gnar's Mega form is a base-stat grant,
        # which also feeds base-AD item scalings like spellblade)
        if "base_attack_damage" in stat_buff:
            # Items that convert base AD to bonus AD (Sterak's Gage) grow
            # with a base-AD buff, exactly as in-game on Mega Gnar. The
            # accessor is linear, so the delta composes.
            steraks_delta = item_effects.steraks_bonus_ad(
                state.items, stat_buff["base_attack_damage"]
            )
            if steraks_delta:
                stats["bonus_attack_damage"] = (
                    stats["bonus_attack_damage"] + steraks_delta
                )
        if "bonus_attack_damage" in stat_buff or "base_attack_damage" in stat_buff:
            stats["attack_damage"] = (
                stats["base_attack_damage"] + stats["bonus_attack_damage"]
            )
        # A movement grant is a term in the ONE move-speed fold, not a
        # second one: the generic add above moved the component, and the
        # displayed number is re-folded by the function the build stats,
        # the runes and the ally bonuses all went through.
        if "move_speed_percent" in stat_buff or "move_speed_flat" in stat_buff:
            stats["move_speed"] = resolve_move_speed(
                stats["move_speed_flat"], stats["move_speed_percent"]
            )
        # Recalculate magic penetration if it was buffed
        if "magic_penetration_percent" in stat_buff:
            resists.magic_pen_percent = stats["magic_penetration_percent"] / 100.0
            resists.resolve_magic()
        # Recalculate armor penetration if it was buffed
        if "armor_penetration_percent" in stat_buff:
            resists.armor_pen_percent = stats["armor_penetration_percent"] / 100.0
            resists.resolve_armor()
        if "armor_penetration_bonus_percent" in stat_buff:
            resists.armor_pen_bonus_percent = (
                stats["armor_penetration_bonus_percent"] / 100.0
            )
            resists.resolve_armor()
        # Bonus health raises max health, and items converting bonus
        # health to AD (Overlord's Bloodmail) grow with the buff
        # (Cho'Gath R's Feast stacks). The accessor is linear, so the
        # delta composes with the item-health conversion already in the
        # build stats.
        if "bonus_health" in stat_buff:
            stats["health"] = stats["health"] + stat_buff["bonus_health"]
            bloodmail_delta = item_effects.bloodmail_bonus_ad(
                state.items, stat_buff["bonus_health"]
            )
            if bloodmail_delta:
                stats["bonus_attack_damage"] = (
                    stats["bonus_attack_damage"] + bloodmail_delta
                )
                stats["attack_damage"] = (
                    stats["base_attack_damage"] + stats["bonus_attack_damage"]
                )
        # A BASE-health grant (Dr. Mundo R) raises max health exactly like
        # a bonus-health one — so %maximum-health mechanics grow with it —
        # but items converting BONUS health to a stat (Overlord's
        # Bloodmail) must NOT see it. That base-vs-bonus split is the
        # whole reason the two keys are separate (the Gnar rule).
        if "base_health" in stat_buff:
            stats["health"] = stats["health"] + stat_buff["base_health"]
        # Recalculate attack speed and auto count if AS was buffed
        if "bonus_attack_speed" in stat_buff:
            bonus_as_pct = stat_buff["bonus_attack_speed"]
            active_duration = (
                ability_sub_payload(ability_info, "auto_attack_override")
            ).get("active_duration")
            _rate_attack_speed_grant(
                state,
                key,
                bonus_as_pct,
                float(active_duration) if active_duration else None,
            )
            stats["attack_speed"] = state.attack_speed
        # A TOTAL-attack-speed multiplier (Bel'Veth True Form) scales the
        # final attack speed, outside the base + ratio x bonus formula.
        # Entries iterate in parse phase order (BUFF-phase bonus-AS
        # grants insert before DAMAGE-phase ultimates), so additive
        # bonus AS is folded in before this multiplies.
        if "total_attack_speed_percent" in stat_buff:
            state.attack_speed *= 1.0 + stat_buff["total_attack_speed_percent"] / 100.0
            stats["attack_speed"] = state.attack_speed
            state.num_auto_attacks = math.floor(
                state.attack_speed
                * state.fight_duration_seconds
                * state.auto_attack_uptime
            )

    # A kit ramp re-rates the swing stream with no flat grant behind it, so
    # nothing above would have reached the rater: the stacks ARE the bonus.
    # An autos-only fight still swings, so it still ramps.
    if _kit_swing_ramp(state) is not None and not state.support_attack_times:
        _rate_attack_speed_grant(state, "", 0.0, None)
        stats["attack_speed"] = state.attack_speed

    if withheld:
        state.notes.append(
            "Autos-only performs no cast, so no ability stat grant applies: "
            + ", ".join(sorted(set(withheld)))
            + ". The mode reports the champion's unbuffed attack speed and "
            "auto damage; pick the timed mode to buy a steroid with a cast."
        )

    # Crit stats — needed by both ability crit scaling (rotation) and the
    # auto-attack simulation.  The item bonus above the game's base multiplier
    # is read once off the build's crit declarations.
    crit_damage_bonus = _crit_profile(state).damage_bonus
    state.crit_chance = min(stats["critical_strike_chance"] / 100.0, 1.0)
    state.crit_multiplier = BASE_CRIT_MULTIPLIER + crit_damage_bonus

    # Champion-owned crit modifiers (Yasuo/Yone P: "total critical strike
    # chance is doubled from all other sources" and "critical strikes deal
    # only 90% of the critical damage champions usually have" — cached P
    # description prose; the 0.9 factor is also the champion's game stat
    # ``criticalStrikeDamageModifier``).  The first ``crit_modifier``
    # payload in the parsed ability rows applies to BOTH the auto-attack
    # simulation and ability parts that declare ``crit_effectiveness``,
    # because both read the shared ``state.crit_chance`` /
    # ``state.crit_multiplier`` resolved here.  Crit chance in excess of
    # 100% converts to bonus AD ("every 1% critical strike chance in
    # excess of 100% is converted into 0.5 bonus attack damage") — the
    # conversion lands on the same stats the auto stream prices.
    for ability_info in state.ability_damages.values():
        crit_modifier = ability_info.get("crit_modifier")
        if not crit_modifier:
            continue
        chance_multiplier = float(
            ability_field(crit_modifier, "crit_chance_multiplier", form="crit_modifier")
        )
        raw_crit_percent = float(stats["critical_strike_chance"])
        state.crit_chance = min(raw_crit_percent / 100.0 * chance_multiplier, 1.0)
        damage_factor = float(
            ability_field(
                crit_modifier, "crit_damage_multiplier_factor", form="crit_modifier"
            )
        )
        state.crit_multiplier = (
            BASE_CRIT_MULTIPLIER + crit_damage_bonus
        ) * damage_factor
        excess_percent = raw_crit_percent * chance_multiplier - 100.0
        per_percent = float(
            ability_field(
                crit_modifier, "excess_crit_bonus_ad_per_percent", form="crit_modifier"
            )
        )
        if excess_percent > 0.0 and per_percent > 0.0:
            stats["bonus_attack_damage"] = (
                stats["bonus_attack_damage"] + excess_percent * per_percent
            )
            stats["attack_damage"] = (
                stats["base_attack_damage"] + stats["bonus_attack_damage"]
            )
        break
