"""Spellblade arming, proc times, and the priced packet."""

from typing import Any

from ... import item_effects
from ...ability_atoms import ability_field
from ...ability_spec import AttackClass

# The interpreter comes in by its one entry point rather than as a module: a
# bare ``spellblade`` here would name the interpreter inside the step the
# engine already calls spellblade.
from ...survival.pricing import AuthoredDeclaration
from ..ledger.event_rows import _damage_type_fields
from ..resists import _mitigate, _resistance_met_fields
from ..results import AutoAttackResult, OnHitResult, RotationResult, SpellbladeResult
from ..state import FightState, _damage_inputs
from .swing_profile import _on_hit_effectiveness


def _spellblade_proc_times(
    rotation: RotationResult,
    effect: item_effects.SpellbladeEffect,
    procs: int,
) -> list[float]:
    """Weave-timed spellblade proc times from the accepted cast timeline.

    Each accepted cast arms one charge (the engine assumes charges
    persist through the item cooldown, as its proc pricing already
    does).  A charge is consumed by the first attack that can take it and
    the cooldown restarts there.  The weave delay is the walk-up to an
    auto attack; an ability that applies on-hit effects *is* the attack
    (Ezreal Q, Senna Q), so one landing at or after the charge is armed
    takes it at that ability's own authored hit time and nothing is walked.
    Returns ``[]`` when the accepted casts cannot reproduce the engine's
    priced proc count — the row then stays coarse rather than carrying an
    event list that contradicts its total.
    """
    if procs <= 0:
        return []
    cast_times = sorted(float(event["time"]) for event in rotation.cast_events)
    onhit_times = sorted(
        float(application.time)
        for application in rotation.ability_item_applications
        if application.on_hit and application.time is not None
    )
    times: list[float] = []
    cooldown_ends = float("-inf")
    for cast_time in cast_times:
        if len(times) == procs:
            break
        armed = max(cast_time, cooldown_ends)
        proc_time = next(
            (hit for hit in onhit_times if hit >= armed), armed + effect.weave_delay
        )
        times.append(proc_time)
        cooldown_ends = proc_time + effect.cooldown
    return times if len(times) == procs else []


def _prepare_spellblade_attack_schedule(
    state: FightState, rotation: RotationResult
) -> None:
    """Prepare Lich Bane's proc timestamps before the auto stream is priced."""
    effect = state.item_spellblade
    if effect is None or effect.bonus_attack_speed_percent <= 0.0:
        return
    onhit_applications = [
        application
        for application in rotation.ability_item_applications
        if application.on_hit
    ]
    consuming_attacks = (
        state.num_auto_attacks + rotation.forced_basic_attacks + len(onhit_applications)
    )
    attack_limit = (
        consuming_attacks
        if state.num_auto_attacks > 0
        else rotation.forced_swing_casts + len(onhit_applications)
    )
    if attack_limit <= 0:
        return
    procs = min(
        rotation.total_ability_casts,
        1 + int(state.fight_duration_seconds / (effect.cooldown + effect.weave_delay)),
        attack_limit,
    )
    proc_times = _spellblade_proc_times(rotation, effect, procs)
    if len(proc_times) != procs:
        return
    state.spellblade_proc_times = tuple(proc_times)
    state.spellblade_attack_speed_percent = effect.bonus_attack_speed_percent


def _add_spellblade_true_rider(
    state: FightState,
    source: item_effects.DamageSource,
    raw_per_proc: float,
    procs: int,
    *,
    proc_times: list[float],
) -> None:
    """Add a champion's true-damage rider on spellblade procs (Corki P).

    The wiki special-cases spellblade effects into Hextech Munitions:
    each proc deals ``spellblade_bonus_true_ratio`` of its own
    PRE-mitigation damage again as true damage. This is ADDED ON TOP of
    the proc; its sibling ``spellblade_true_ratio`` (Camille Q2) instead
    CONVERTS that share of the proc out of the item's own damage type.
    The rider shares the procs' weave-timed events when they exist.
    """
    ratio = max(
        (
            ability_field(info, "spellblade_bonus_true_ratio")
            for info in state.ability_damages.values()
        ),
        default=0.0,
    )
    if ratio <= 0 or procs <= 0:
        return

    rider_total = raw_per_proc * ratio * procs
    state.breakdown[f"{source.breakdown_key}_bonus_true"] = {
        "name": f"{source.display_name} (bonus true damage)",
        "count": procs,
        "damage_per_hit": rider_total / procs,
        "unit": "procs",
        "total_damage": rider_total,
        "damage_type": "true",
    }
    if len(proc_times) == procs:
        state.breakdown[f"{source.breakdown_key}_bonus_true"]["damage_events"] = [
            {
                "time": proc_time,
                "damage": rider_total / procs,
                "damage_type": "true",
            }
            for proc_time in proc_times
        ]
    state.total_damage += rider_total


def _spellblade_declaration(mechanic_id: str, raw_amount: float) -> tuple[Any, ...]:
    """One spellblade packet's declaration: rule, magnitude, attack class.

    ``AttackClass.OTHER`` is measured, not defaulted: a spellblade proc reaches
    the target through :func:`_mitigate` alone, never through
    :func:`_mitigate_basic_attack_swing`, so it earns no basic amp, no
    target-side swing term and no part amp.  *raw_amount* already carries the
    consuming attack's on-hit effectiveness, which allocates rather than amps."""
    return tuple(
        AuthoredDeclaration(
            mechanic_id,
            raw_amount,
            AttackClass.OTHER.value,
        )
    )


def _add_spellblade_damage(
    state: FightState,
    rotation: RotationResult,
    autos: AutoAttackResult,
    on_hits: OnHitResult,
) -> SpellbladeResult:
    """Add spellblade proc damage and Dusk and Dawn's double on-hit.

    Procs are limited by ability casts, the spellblade's cooldown plus
    weave delay, and the fight's auto count. Also totals the extra on-hit
    stack applications (Dusk and Dawn double on-hits, double-shot autos)
    that accelerate Kraken Slayer / Hullbreaker stacking later.

    Spellblade procs on replaced autos (Azir soldiers) at the override's
    on-hit effectiveness (game-verified: Lich Bane procs at 50% damage).
    """
    resists = state.resists
    result = SpellbladeResult()

    effect = state.item_spellblade
    if effect is not None:
        result.item = effect.source.item_name

    # A spellblade charge is consumed by any basic attack — the auto
    # stream when one exists, plus attacks forced by empowered-auto
    # casts when it doesn't (Camille Q, Blitzcrank E in one-rotation) —
    # and by ability hits that apply item on-hits (wiki: spellblade can
    # be "applied by an ability that triggers on-hit effects" — Ezreal
    # Q, Bel'Veth Q). Without those, an auto-less fight showed zero
    # Sheen procs for the champions built around them.
    onhit_applications = [a for a in rotation.ability_item_applications if a.on_hit]
    consuming_attacks = (
        state.num_auto_attacks + rotation.forced_basic_attacks + len(onhit_applications)
    )
    if effect is not None and consuming_attacks > 0:
        source = effect.source
        sb_effectiveness = _on_hit_effectiveness(state)
        if state.num_auto_attacks == 0 and onhit_applications:
            # No auto stream: procs are consumed by the ability
            # applications (and any forced attacks). Assume procs land
            # on the highest-effectiveness consumers first — the same
            # first-lands assumption the true-conversion accounting
            # below makes.
            sb_effectiveness = max(
                [a.effectiveness for a in onhit_applications]
                + ([sb_effectiveness] if rotation.forced_basic_attacks else [])
            )
        raw_sb = source.raw_damage(_damage_inputs(state)) * sb_effectiveness
        effective_sb_cd = effect.cooldown + effect.weave_delay

        result.damage_per_proc = _mitigate(
            raw_sb, source.damage_type, resists, state.magic_amp
        )

        # Number of procs: limited by ability casts and cooldown. With no
        # auto stream the consuming hits are the attacks casts forced —
        # a charge is armed per cast, so a cast that forces a whole burst
        # (Jayce's 3 Hyper Charge attacks) still spends just one — plus
        # the on-hit ability applications (each is a real separate hit;
        # the cast cap already stops a multi-hit cast from double-spending).
        attack_limit = (
            consuming_attacks
            if state.num_auto_attacks > 0
            else rotation.forced_swing_casts + len(onhit_applications)
        )
        result.procs = min(
            rotation.total_ability_casts,
            1 + int(state.fight_duration_seconds / effective_sb_cd),
            attack_limit,
        )

        # True-damage conversion (Camille Q2): an entry flagged
        # ``spellblade_true_ratio`` converts the proc its empowered
        # attack consumes — that ratio of the proc becomes unmitigated
        # true damage, the rest keeps the item's own type. One converted
        # proc per cast of the flagged entry (assumes procs land on the
        # flagged casts first — exact whenever procs aren't starved).
        converted_ratio = 0.0
        converted = 0
        for key, info in state.ability_damages.items():
            ratio = ability_field(info, "spellblade_true_ratio")
            if ratio > 0:
                converted_ratio = max(converted_ratio, ratio)
                converted += state.breakdown.get(key, {}).get("casts", 0)
        converted = min(converted, result.procs)
        converted_per_proc = raw_sb * converted_ratio + result.damage_per_proc * (
            1.0 - converted_ratio
        )

        plain = result.procs - converted
        sb_total = result.damage_per_proc * plain + converted_per_proc * converted

        # Weave-timed events: authored only when the accepted casts
        # reproduce the priced proc count, and only for unconverted
        # builds (the true-conversion split's proc-to-cast assignment
        # is an assumption, not a certified order).
        proc_times = _spellblade_proc_times(rotation, effect, result.procs)

        if plain > 0 or converted == 0:  # unconverted builds keep the row as-is
            plain_row: dict[str, Any] = {
                "name": source.display_name,
                "count": plain,
                "damage_per_hit": result.damage_per_proc,
                "unit": "procs",
                "total_damage": result.damage_per_proc * plain,
                "damage_type": source.damage_type,
            }
            if plain > 0:
                # This row is the pair engine's preview of a number the
                # coupled walk owns: the roster composition reads the stamp
                # and takes the figure above out of every total it composes,
                # while the pair fight's own receipt publishes it unchanged.
                # The row-level declaration is what a *coarse* row hands the
                # walk: one whose procs landed on no certifiable weave
                # schedule, so it authors no event of its own and the
                # reconstruction synthesizes one (``_row_declaration_share``).
                plain_row["pair_preview_of"] = source.previewed_mechanic()
                plain_row["declared"] = _spellblade_declaration(
                    source.previewed_mechanic(), raw_sb * plain
                )
            state.breakdown[source.breakdown_key] = plain_row
            if proc_times:
                # Every proc of one fight shares a magnitude: the engine
                # prices one raw value and multiplies its mitigated figure by
                # the proc count, so each authored event carries that value
                # rather than a share of the row's total.  A converted build
                # was priced on the assumption that procs land on the flagged
                # casts first, so the plain row's events are the LAST
                # ``plain`` boundaries of the same certified weave schedule —
                # the authored assignment restates the priced one.
                plain_row["damage_events"] = [
                    {
                        "time": proc_time,
                        "damage": result.damage_per_proc,
                        "damage_type": source.damage_type,
                        **(
                            {
                                "declared": _spellblade_declaration(
                                    source.previewed_mechanic(), raw_sb
                                )
                            }
                            if plain > 0
                            else {}
                        ),
                        **_resistance_met_fields(source.damage_type, resists),
                    }
                    for proc_time in proc_times[converted:]
                ]
        if converted > 0:
            converted_by_type = {"true": raw_sb * converted_ratio * converted}
            if converted_ratio < 1.0:
                converted_by_type[source.damage_type] = (
                    result.damage_per_proc * (1.0 - converted_ratio) * converted
                )
            state.breakdown[f"{source.breakdown_key}_true"] = {
                "name": f"{source.display_name} (true conversion)",
                "count": converted,
                "damage_per_hit": converted_per_proc,
                "unit": "procs",
                "total_damage": converted_per_proc * converted,
                **_damage_type_fields(converted_by_type),
            }
            if proc_times:
                # The first ``converted`` weave boundaries carry the procs
                # the pricing converted; each splits into its unmitigated
                # true share and (below 100% conversion) the item-typed rest.
                state.breakdown[f"{source.breakdown_key}_true"]["damage_events"] = [
                    {
                        "time": proc_time,
                        "damage": amount,
                        "damage_type": dtype,
                        **_resistance_met_fields(dtype, resists),
                    }
                    for proc_time in proc_times[:converted]
                    for dtype, amount in (
                        ("true", raw_sb * converted_ratio),
                        (
                            source.damage_type,
                            result.damage_per_proc * (1.0 - converted_ratio),
                        ),
                    )
                    if amount > 0
                ]
        state.total_damage += sb_total
        _add_spellblade_true_rider(
            state, source, raw_sb, result.procs, proc_times=proc_times
        )

        # Spellblade siblings are resolved from the same accepted proc event
        # as the damage.  They are informational resource/sustain outputs in
        # the damage calculator (the surrounding participant ledger owns
        # resource admission and health mutation), but are never silently
        # dropped from the item packet.
        stats = state.champion_stats
        if effect.mana_restore_base_ad_ratio or effect.mana_restore_crit_ratio:
            mana_per_proc = effect.mana_restore_base_ad_ratio * stats[
                "base_attack_damage"
            ] + effect.mana_restore_crit_ratio * min(
                stats["critical_strike_chance"] / 100.0, 1.0
            )
            result.mana_restored = mana_per_proc * result.procs
            state.breakdown[f"mana_{result.item}"] = {
                "name": f"{result.item} (Manaflow)",
                "count": result.procs,
                "proc_times": list(proc_times),
                "amount_per_proc": mana_per_proc,
                "total_amount": result.mana_restored,
                "unit": "mana",
            }
        if effect.self_heal_ap_ratio or effect.self_heal_bonus_health_ratio:
            heal_per_proc = (
                effect.self_heal_ap_ratio * stats["ability_power"]
                + effect.self_heal_bonus_health_ratio * stats["bonus_health"]
            )
            result.self_healing = heal_per_proc * result.procs
            state.breakdown[f"heal_{result.item}"] = {
                "name": f"{result.item} (self-heal)",
                "count": result.procs,
                "proc_times": list(proc_times),
                "amount_per_proc": heal_per_proc,
                "total_amount": result.self_healing,
                "unit": "health",
            }

    # ── Double on-hit from spellblade (Dusk and Dawn) ──
    if effect is not None and result.procs > 0 and effect.double_on_hit:
        result.double_on_hit_procs = result.procs
        extra_by_type = {
            dtype: amount * result.double_on_hit_procs
            for dtype, amount in on_hits.static_on_hit_by_type().items()
        }
        # What each producer of the doubled application contributed, for the
        # reader that has to explain the row: the row's own damage is a sum
        # over producers of one damage type, so the attribution cannot live
        # on the typed events.  Receipt only; no allow list publishes it.
        extra_shares = [
            {
                "producer": share.producer_id,
                "damage_type": share.damage_type,
                "damage": share.mitigated * result.double_on_hit_procs,
                "raw_damage": share.raw * result.double_on_hit_procs,
            }
            for share in on_hits.static_on_hit_shares
            if share.mitigated > 0.0
        ]
        # The same pool read pre-mitigation, so one doubled application can
        # state the raw it was priced from rather than its mitigated amount.
        raw_by_type: dict[str, float] = {}
        for share in on_hits.static_on_hit_shares:
            raw_by_type[share.damage_type] = (
                raw_by_type.get(share.damage_type, 0.0) + share.raw
            )

        # Current-health extra procs use the fight's average per-hit damage.
        if on_hits.has_current_health_on_hit and state.num_auto_attacks > 0:
            ch_type = on_hits.current_health_damage_type
            extra_by_type[ch_type] = extra_by_type.get(ch_type, 0.0) + (
                on_hits.current_health_on_hit_avg * result.double_on_hit_procs
            )
            # That average is of mitigated procs and states no raw of its
            # own, so the type it lands on states none either.
            raw_by_type.pop(ch_type, None)

        extra_on_hit = sum(extra_by_type.values())
        if extra_on_hit > 0:
            state.breakdown[f"double_on_hit_{result.item}"] = {
                "name": f"{result.item} (Double On-Hit)",
                "count": result.double_on_hit_procs,
                "damage_per_hit": extra_on_hit / result.double_on_hit_procs,
                "unit": "procs",
                "total_damage": extra_on_hit,
                **_damage_type_fields(extra_by_type),
                "on_hit_shares": extra_shares,
            }
            # Each double application rides the attack that consumed the
            # charge, at the weave-timed proc boundary the spellblade
            # row itself was priced on; every proc doubles the same
            # per-hit packet, so each event is one proc's typed share.
            if len(proc_times) == result.double_on_hit_procs:
                state.breakdown[f"double_on_hit_{result.item}"]["damage_events"] = [
                    {
                        "time": proc_time,
                        "damage": amount / result.double_on_hit_procs,
                        "damage_type": dtype,
                        **(
                            {"raw_damage": raw_by_type[dtype]}
                            if dtype in raw_by_type
                            else {}
                        ),
                        **_resistance_met_fields(dtype, resists),
                    }
                    for proc_time in proc_times
                    for dtype, amount in extra_by_type.items()
                    if amount > 0
                ]
            state.total_damage += extra_on_hit

    # Double shot on-hit stacking: each auto generates an extra on-hit
    # application, accelerating Kraken Slayer / Hullbreaker procs.
    if autos.double_shot_info:
        result.double_on_hit_procs += state.num_auto_attacks

    return result
