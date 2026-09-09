"""Per-swing crit rolls with the overlapping riders."""

import random
from typing import Any

from ...ability_atoms import ability_field
from ...ability_spec import AttackClass
from ...interpreters import charged_strike
from ..ledger.event_rows import _ledger_total
from ..mitigation import _mitigate_basic_attack_swing
from ..resists import _mitigate
from ..results import AutoAttackResult
from ..rotation.shaped_charge import _strike_declaration
from ..state import FightState, _crit_profile
from .swing_profile import (
    _auto_swing_bonus_ad,
    _basic_attack_true_rider,
    _find_auto_attack_override,
)
from .swing_schedule import _auto_attack_timestamps


def _simulate_auto_attacks(state: FightState) -> AutoAttackResult:
    """Simulate each auto attack individually, rolling (or expecting) crits.

    Handles champion auto-attack overrides (Ashe: crit chance converts to
    bonus damage on every auto; Azir: soldier attacks replace the auto
    stream with flat magic damage that cannot crit), Fiendhunter Bolts
    empowered autos
    (guaranteed-crit true damage / reduced non-crits), Sundered Sky's
    forced first-auto crit, double-shot passives (Akshan), and the basic
    damage amplifier (Hexoptics). In deterministic mode crits are blended
    at expected value instead of rolled.
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks
    empowered_autos = state.empowered_autos
    ultimate_auto_buff = state.declared.charged_strikes.empowered_auto_buff
    crit_chance = state.crit_chance
    crit_multiplier = state.crit_multiplier
    basic_amp = state.basic_amp
    deterministic = state.deterministic

    attack_damage = state.champion_stats["attack_damage"]

    # Detect auto_attack_override (e.g. Ashe passive — crit chance converts
    # to bonus damage instead of crit strikes; Q changes AD ratio).
    auto_attack_override = _find_auto_attack_override(state.ability_damages)

    # Detect champion double-shot passive (e.g. Akshan — second auto per
    # attack at reduced AD ratio, applies on-hits and can crit).
    double_shot_info: dict[str, Any] | None = None
    for _ds_info in state.ability_damages.values():
        if "double_shot" in _ds_info:
            double_shot_info = _ds_info["double_shot"]
            break

    # A bounded set of attacks may replace their normal physical swing with
    # one modified basic-damage instance (Galio's Colossal Smash). The
    # module supplies only the non-AD bonus; the ordinary swing path below
    # continues to own crits, Sundered Sky, and mid-fight AD changes.
    conversion_info: dict[str, Any] | None = None
    for _conversion_entry in state.ability_damages.values():
        if "auto_attack_conversion" in _conversion_entry:
            conversion_info = _conversion_entry["auto_attack_conversion"]
            break
    converted_auto_limit = min(
        num_auto_attacks,
        (
            max(0, int(ability_field(conversion_info, "count", form="conversion")))
            if conversion_info
            else 0
        ),
    )

    # Simulate each auto attack individually, rolling for crits.  The two
    # swing totals are not accumulated here: they are read off the event
    # lists below, because the row IS the sum of its own ledger.
    fiendhunter_true_total = 0.0
    passive_true_total = 0.0  # champion rider (Corki P), % of the raw swing
    num_crits = 0
    crit_damage_per_hit = 0.0
    non_crit_damage_per_hit = 0.0

    fh_reduced_crit = (
        ultimate_auto_buff.reduced_crit_ratio if ultimate_auto_buff is not None else 0.0
    )
    fh_true_ratio = (
        ultimate_auto_buff.natural_crit_true_damage_ratio
        if ultimate_auto_buff is not None
        else 0.0
    )

    first_auto_crit = _crit_profile(state).forced_crit
    ss_reduced_crit = (
        first_auto_crit.reduced_ratio if first_auto_crit is not None else 0.0
    )

    sundered_sky_damage_diff = 0.0  # post-target: + = bonus, - = lost damage

    # Ashe-style override: crit chance converts to bonus AD ratio on every
    # auto instead of random crit strikes.  ad_ratio replaces the normal 1.0.
    # Azir-style override: replace_raw substitutes the whole auto formula
    # with a flat module-computed amount (its own damage type, no crits).
    override_ad_ratio = 0.0
    override_crit_as_bonus = False
    override_replace_raw: float | None = None
    override_damage_type = "physical"
    damage_ratio = 1.0
    passive_true_ratio, passive_true_name = _basic_attack_true_rider(
        state.ability_damages
    )
    q_window_end = state.q_window_end
    if auto_attack_override:
        override_ad_ratio = ability_field(
            auto_attack_override, "ad_ratio", form="auto_attack_override"
        )
        override_crit_as_bonus = ability_field(
            auto_attack_override, "crit_as_bonus", form="auto_attack_override"
        )
        override_replace_raw = auto_attack_override.get("replace_raw")
        override_damage_type = ability_field(
            auto_attack_override, "damage_type", form="auto_attack_override"
        )
        if not override_replace_raw and q_window_end > 0.0:
            # P1 Slice 11: the flurry ratio applies only inside the Q
            # active window [0, q_window_end) — the post-window swings
            # revert to the normal 1.0 ratio (Frost Shot's crit-as-bonus
            # stays on for every swing).  The hoisted override_ad_ratio
            # stays the flurry value; the per-swing swing_window_ratio
            # below applies the window.
            pass
        # Flat modifier on ALL basic-attack damage (Bel'Veth passive:
        # 75%): scaling the AD every auto branch reads covers normal,
        # crit, empowered, forced-crit, and double-shot attacks alike.
        damage_ratio = ability_field(
            auto_attack_override, "damage_ratio", form="auto_attack_override"
        )
        attack_damage *= damage_ratio

    # A stack-triggered bonus-AD steroid (Darius' Noxian Might) only
    # covers part of the fight, so each swing is priced at the AD its own
    # timestamp saw. Without such a buff every swing_ad below is exactly
    # ``attack_damage``, as it always was.
    swing_bonus_ad = _auto_swing_bonus_ad(state, damage_ratio)
    auto_times = _auto_attack_timestamps(state)
    auto_events: list[dict[str, Any]] = []
    fiendhunter_events: list[dict[str, Any]] = []
    passive_true_events: list[dict[str, Any]] = []
    converted_auto_events: list[dict[str, Any]] = []
    converted_natural_crits = 0

    def converted_swing_damage(raw_ad: float, *, critical: bool) -> float:
        """Price one modified attack, reducing only its AD crit component."""
        assert conversion_info is not None
        adjusted_ad = raw_ad
        if critical:
            adjusted_ad *= state.target_critical_strike_damage_multiplier
        return _mitigate_basic_attack_swing(
            state,
            float(ability_field(conversion_info, "bonus_raw", form="conversion"))
            + adjusted_ad,
            str(ability_field(conversion_info, "damage_type", form="conversion")),
        )

    for i in range(num_auto_attacks):
        attack_time = auto_times[i] if i < len(auto_times) else 0.0
        swing_ad = attack_damage + swing_bonus_ad(i)
        if override_replace_raw is not None:
            # Full auto replacement (Azir W): flat raw per attack, the
            # override's damage type, cannot crit — crit items, the
            # empowered-auto item branches, and Sundered Sky's forced
            # first-auto crit (game-verified: not applied by soldier
            # attacks at all) never apply.
            mitigated = _mitigate(
                override_replace_raw, override_damage_type, resists, state.magic_amp
            )
            non_crit_damage_per_hit = mitigated
            auto_events.append(
                {
                    "time": attack_time,
                    "damage_type": override_damage_type,
                    "damage": mitigated,
                }
            )
            continue
        is_empowered = ultimate_auto_buff is not None and i < empowered_autos
        is_sundered = first_auto_crit is not None and i == 0
        natural_crit = False if deterministic else random.random() < crit_chance

        if natural_crit:
            num_crits += 1

        deterministic_outcomes: list[tuple[float, float, bool]] | None = None
        sundered_normal_raw: float | None = None

        swing_window_ratio = (
            override_ad_ratio
            if q_window_end <= 0.0
            or (state.q_window_start <= attack_time < q_window_end)
            else 1.0
        )
        if override_crit_as_bonus:
            # Crit chance converts to bonus damage on every auto (e.g. Ashe).
            # Passive: "bonus damage equal to X% of the attack's damage."
            # The bonus is multiplicative with the attack's base damage ratio,
            # because each Q arrow individually applies Frost Shot.
            # Formula: AD * ad_ratio * (1 + crit_chance * (crit_mult - 1))
            # The per-swing ratio honors the Q active window.
            # Without IE: AD * ratio * (1 + crit_chance)
            # With IE:    AD * ratio * (1 + crit_chance * 1.30)
            bonus_crit_ratio = crit_multiplier - 1.0
            raw_phys = (
                swing_ad * swing_window_ratio * (1 + crit_chance * bonus_crit_ratio)
            )
            raw_true = 0.0
        elif is_empowered:
            if deterministic:
                # Expected-value for empowered autos
                raw_phys_crit = swing_ad * crit_multiplier
                raw_true_crit = raw_phys_crit * fh_true_ratio
                raw_phys_no = swing_ad * crit_multiplier * fh_reduced_crit
                raw_phys = crit_chance * raw_phys_crit + (1 - crit_chance) * raw_phys_no
                raw_true = crit_chance * raw_true_crit
                deterministic_outcomes = [
                    (crit_chance, raw_phys_crit, True),
                    (1.0 - crit_chance, raw_phys_no, True),
                ]
            elif natural_crit:
                # Full crit + bonus true damage
                raw_phys = swing_ad * crit_multiplier
                raw_true = raw_phys * fh_true_ratio
            else:
                # Reduced crit (80% of normal crit damage)
                raw_phys = swing_ad * crit_multiplier * fh_reduced_crit
                raw_true = 0.0
            fiendhunter_true_total += raw_true
        elif is_sundered:
            # Sundered Sky: forced crit at reduced ratio, overrides natural crit
            raw_phys = swing_ad * crit_multiplier * ss_reduced_crit
            # Calculate what the auto would have dealt without Sundered Sky
            if deterministic:
                normal_raw = swing_ad * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
            elif natural_crit:
                normal_raw = swing_ad * crit_multiplier
            else:
                normal_raw = swing_ad
            sundered_normal_raw = normal_raw
            raw_true = 0.0
        else:
            if deterministic:
                # Expected-value: blend crit and non-crit damage
                raw_phys = swing_ad * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
                deterministic_outcomes = [
                    (crit_chance, swing_ad * crit_multiplier, True),
                    (1.0 - crit_chance, swing_ad, False),
                ]
            elif natural_crit:
                raw_phys = swing_ad * crit_multiplier
            else:
                raw_phys = swing_ad
            raw_true = 0.0

        if deterministic_outcomes is not None:
            if i < converted_auto_limit:
                mitigated = sum(
                    weight * converted_swing_damage(outcome_raw, critical=critical)
                    for weight, outcome_raw, critical in deterministic_outcomes
                )
            else:
                mitigated = sum(
                    weight
                    * _mitigate_basic_attack_swing(
                        state, outcome_raw, critical_strike=critical
                    )
                    for weight, outcome_raw, critical in deterministic_outcomes
                )
        else:
            converted_critical = not override_crit_as_bonus and (
                natural_crit or is_empowered or is_sundered
            )
            if i < converted_auto_limit:
                mitigated = converted_swing_damage(
                    raw_phys,
                    critical=converted_critical,
                )
            else:
                mitigated = _mitigate_basic_attack_swing(
                    state,
                    raw_phys,
                    critical_strike=converted_critical,
                )

        if sundered_normal_raw is not None:
            if deterministic:
                normal_mitigated = crit_chance * (
                    converted_swing_damage(swing_ad * crit_multiplier, critical=True)
                    if i < converted_auto_limit
                    else _mitigate_basic_attack_swing(
                        state,
                        swing_ad * crit_multiplier,
                        critical_strike=True,
                    )
                ) + (1.0 - crit_chance) * (
                    converted_swing_damage(swing_ad, critical=False)
                    if i < converted_auto_limit
                    else _mitigate_basic_attack_swing(state, swing_ad)
                )
            else:
                normal_mitigated = (
                    converted_swing_damage(
                        sundered_normal_raw,
                        critical=natural_crit,
                    )
                    if i < converted_auto_limit
                    else _mitigate_basic_attack_swing(
                        state,
                        sundered_normal_raw,
                        critical_strike=natural_crit,
                    )
                )
            sundered_sky_damage_diff = mitigated - normal_mitigated
        if i < converted_auto_limit:
            converted_natural_crits += int(natural_crit)
            converted_auto_events.append(
                {
                    "time": attack_time,
                    "damage_type": str(
                        ability_field(conversion_info, "damage_type", form="conversion")
                    ),
                    "damage": mitigated,
                }
            )
        else:
            auto_events.append(
                {
                    "time": attack_time,
                    "damage_type": "physical",
                    "damage": mitigated,
                    # The roll this swing actually made, carried on the
                    # swing itself: the row's crit split is a count of
                    # these, and a later site that removes swings has to
                    # recount rather than rescale (issue: the ledger and
                    # the row must describe ONE realization).
                    "critical_strike": natural_crit,
                }
            )
        if raw_true > 0:
            assert ultimate_auto_buff is not None
            fiendhunter_events.append(
                {
                    "time": attack_time,
                    "damage_type": "true",
                    "damage": raw_true * basic_amp,
                    # The one charged strike whose packet earns a part amp:
                    # this true instance rides the swing, so the basic amp
                    # multiplies it below and the declaration says so with
                    # its class rather than pre-multiplying the magnitude
                    # (umbrella Amendment M, Ruling 1's ordering).
                    "declared": _strike_declaration(
                        ultimate_auto_buff.item_name,
                        raw_true,
                        AttackClass.BASIC_ATTACK,
                    ),
                }
            )
        # Champion rider: a share of this swing's PRE-mitigation damage
        # again as true damage (Corki P). Riding raw_phys carries the
        # attack's crit multiplier, exactly as the wiki describes.
        passive_true_total += raw_phys * passive_true_ratio
        if raw_phys * passive_true_ratio > 0:
            passive_true_events.append(
                {
                    "time": attack_time,
                    "damage_type": "true",
                    "damage": raw_phys * passive_true_ratio * basic_amp,
                }
            )

        # Track per-hit damage for crits vs non-crits (last value wins;
        # all crits deal the same and all non-crits deal the same)
        if deterministic:
            non_crit_damage_per_hit = mitigated
        elif natural_crit:
            crit_damage_per_hit = mitigated
        else:
            non_crit_damage_per_hit = mitigated

    # Apply basic damage amplification (e.g. Hexoptics C44 Magnification)
    fiendhunter_true_total *= basic_amp
    # Corki's true instance is basic damage in-game, like the physical one.
    passive_true_total *= basic_amp

    auto_physical_total = _ledger_total(auto_events)
    converted_auto_total = _ledger_total(converted_auto_events)
    auto_total = auto_physical_total + converted_auto_total
    auto_damage_per_hit = auto_total / num_auto_attacks if num_auto_attacks > 0 else 0.0
    ordinary_auto_count = num_auto_attacks - converted_auto_limit
    ordinary_crits = max(0, num_crits - converted_natural_crits)
    num_non_crits = ordinary_auto_count - ordinary_crits

    auto_name = "Auto Attacks"
    auto_damage_type = "physical"
    if override_replace_raw is not None:
        auto_name = auto_attack_override.get("name", auto_name)
        auto_damage_type = override_damage_type

    breakdown["auto_attacks"] = {
        "name": auto_name,
        "count": ordinary_auto_count,
        "num_crits": ordinary_crits,
        "num_non_crits": num_non_crits,
        "crit_damage_per_hit": crit_damage_per_hit if ordinary_crits > 0 else None,
        "non_crit_damage_per_hit": (
            non_crit_damage_per_hit if num_non_crits > 0 else None
        ),
        "damage_per_hit": (
            auto_physical_total / ordinary_auto_count
            if ordinary_auto_count > 0
            else 0.0
        ),
        "total_damage": auto_physical_total,
        "damage_type": auto_damage_type,
        # ``auto_events`` also contains swings consumed by a champion-owned
        # empowered/modified attack row.  Those swings are accounted for in
        # that row (or forced cast entry), so keep this ledger aligned with
        # the ordinary-auto aggregate before certifying its event total.
        "damage_events": auto_events[:ordinary_auto_count],
        "event_phase": "auto",
    }
    if conversion_info is not None and converted_auto_limit > 0:
        breakdown["on_hit_ability_passive"] = {
            "name": str(ability_field(conversion_info, "name", form="conversion")),
            "count": converted_auto_limit,
            "damage_per_hit": converted_auto_total / converted_auto_limit,
            "total_damage": converted_auto_total,
            "damage_type": str(
                ability_field(conversion_info, "damage_type", form="conversion")
            ),
            "damage_events": converted_auto_events,
            "event_phase": "auto",
            "detail": (
                f"{converted_auto_limit} modified basic attack"
                f"{'' if converted_auto_limit == 1 else 's'}; includes the swing"
            ),
        }
    if ultimate_auto_buff is not None and empowered_autos > 0:
        breakdown["auto_attacks"]["empowered_count"] = empowered_autos

    # Sundered Sky breakdown: show the damage difference on first auto.
    # Replaced autos (Azir soldiers) never consume Sundered Sky — no row.
    if (
        first_auto_crit is not None
        and num_auto_attacks > 0
        and override_replace_raw is None
    ):
        mitigated_diff = abs(sundered_sky_damage_diff)
        if sundered_sky_damage_diff > 0:
            ss_note = (
                f"+{mitigated_diff:.0f} bonus damage (non-crit turned into "
                f"{ss_reduced_crit * 100:.0f}% crit)"
            )
        elif sundered_sky_damage_diff < 0:
            ss_note = (
                f"-{mitigated_diff:.0f} lost damage (normal crit overridden to "
                f"{ss_reduced_crit * 100:.0f}% crit)"
            )
        else:
            ss_note = "No damage change"
        breakdown["sundered_sky"] = {
            "name": f"{first_auto_crit.owner} (Lightshield Strike)",
            "total_damage": mitigated_diff,
            "detail": ss_note,
            "informational": True,
        }

    if fiendhunter_true_total > 0:
        assert ultimate_auto_buff is not None
        breakdown["fiendhunter_true_damage"] = {
            "name": f"{ultimate_auto_buff.item_name} (true damage)",
            "count": empowered_autos,
            "total_damage": fiendhunter_true_total,
            "damage_type": "true",
            # A ``charged_strike`` preview like the four other sites author:
            # the pair engine's figure leaves every roster total and the
            # events below carry the declarations the coupled walk prices.
            "pair_preview_of": charged_strike.strike_mechanic_id(
                ultimate_auto_buff.item_name
            ),
            # The row's own magnitude is the pre-amp one, because the class
            # above is what earns the amp: ``fiendhunter_true_total`` has
            # already been multiplied by ``basic_amp`` for display.
            "declared": _strike_declaration(
                ultimate_auto_buff.item_name,
                fiendhunter_true_total / basic_amp,
                AttackClass.BASIC_ATTACK,
            ),
            "damage_events": fiendhunter_events,
            "event_phase": "auto",
        }

    if passive_true_total > 0:
        breakdown["auto_attacks_true_damage"] = {
            "name": f"{passive_true_name} (true damage)",
            "count": num_auto_attacks,
            "damage_per_hit": passive_true_total / num_auto_attacks,
            "total_damage": passive_true_total,
            "damage_type": "true",
            "damage_events": passive_true_events,
            "event_phase": "auto",
        }

    # Add basic damage amp breakdown entry (informational — already applied)
    if basic_amp > 1.0:
        amp_name = state.basic_amp_owner
        basic_amp_bonus = (
            (auto_total + fiendhunter_true_total + passive_true_total)
            * (basic_amp - 1.0)
            / basic_amp
        ) + state.basic_amp_ability_bonus
        breakdown[f"basic_amp_{amp_name}"] = {
            "name": f"Damage Amplification ({amp_name})",
            "multiplier": basic_amp,
            "total_damage": basic_amp_bonus,
            "detail": "included in the auto attack / basic damage rows above",
            "informational": True,
        }

    # Double shot: second auto per attack at reduced AD (e.g. Akshan passive)
    double_shot_total = 0.0
    if double_shot_info and num_auto_attacks > 0:
        ds_ratio = ability_field(double_shot_info, "ad_ratio", form="double_shot")
        ds_crits = 0
        double_shot_events: list[dict[str, Any]] = []
        for i in range(num_auto_attacks):
            ds_ad = attack_damage * ds_ratio
            if deterministic:
                ds_crit = False
                event_damage = crit_chance * _mitigate_basic_attack_swing(
                    state,
                    ds_ad * crit_multiplier,
                    critical_strike=True,
                ) + (1.0 - crit_chance) * _mitigate_basic_attack_swing(state, ds_ad)
                double_shot_total += event_damage
                double_shot_events.append(
                    {
                        "time": auto_times[i] if i < len(auto_times) else 0.0,
                        "damage_type": "physical",
                        "damage": event_damage,
                        "event_precision": "exact",
                    }
                )
                continue
            ds_crit = random.random() < crit_chance
            if ds_crit:
                ds_crits += 1
                raw_ds = ds_ad * crit_multiplier
            else:
                raw_ds = ds_ad
            event_damage = _mitigate_basic_attack_swing(
                state,
                raw_ds,
                critical_strike=ds_crit,
            )
            double_shot_total += event_damage
            double_shot_events.append(
                {
                    "time": auto_times[i] if i < len(auto_times) else 0.0,
                    "damage_type": "physical",
                    "damage": event_damage,
                    "event_precision": "exact",
                }
            )

        ds_non_crits = num_auto_attacks - ds_crits
        breakdown["double_shot"] = {
            "name": ability_field(double_shot_info, "name", form="double_shot"),
            "count": num_auto_attacks,
            "num_crits": ds_crits,
            "num_non_crits": ds_non_crits,
            "total_damage": double_shot_total,
            "damage_type": "physical",
            "damage_events": double_shot_events,
            "event_phase": "auto",
        }

    state.total_damage += (
        auto_total + fiendhunter_true_total + passive_true_total + double_shot_total
    )

    return AutoAttackResult(
        auto_damage_per_hit=auto_damage_per_hit,
        double_shot_info=double_shot_info,
    )
