"""Briar — slot map for the archetype engine.

Why each slot is non-generic:
- P (Crimson Curse) is a hit-driven stacking bleed no on-hit archetype
  can express: every attack AND ability application adds a stack (max
  5; extra stacks tick at 25%), reapplying refreshes the shared 5s
  duration. The JSON parse is degraded (a jumble of "Per-Level
  Scaling"/"Bonus Damage" per-tick and per-window arrays with empty
  units), so the wiki formula is hand-authored here and the fight
  engine's hit-timeline DoT (``stacking_dot`` + ``applies_dot_stack``,
  damage.py Case 4) owns the stack/tick accounting.
- Q (Head Rush) carries three riders beside its damage read: it applies
  item on-hits at 100% as a real attack (``triggers`` on_hit AND
  on_attack, per the wiki data template), applies one bleed stack, and
  shreds 10-20% armor+MR as a ``target_debuff`` (the Kog'Maw rule: the
  fight engine applies it after Q's own damage).
- W (Blood Frenzy) splits into two slots. "W_frenzy" is the zero-damage
  BUFF entry (+55-95% attack speed, +24-60% move speed; the cleave is
  skipped — it never hits the primary target). "W" is Snack Attack, the
  frenzy's empowered NEXT basic attack (``empowers_next_auto``, once
  per W cast — the Alistar rule), whose missing-health scaling resolves
  the compound "% (+2.5% per 100 bonus AD) of the target's missing
  health" unit against the shared ``target_missing_hp_pct`` option
  (Bel'Veth's missing-health pattern). Both exist only while the
  frenzy is active (``blood_frenzy_active``; R re-triggers the frenzy
  for its whole duration, so ON is the all-in default).
- E (Chilling Scream) is assumed fully charged ("Maximum Magic Damage";
  the classifier's first-damage pick and the generic rank default were
  both wrong), with the terrain-collision bonus behind the
  ``e_wall_collision`` option. Applies a bleed stack; does NOT apply
  item on-hits (verified in the raw data template).
- R (Certain Death) is the explosion damage ("Magic Damage") plus stat
  buffs the JSON only partly holds: life steal and move speed are
  leveling entries, the +20% total AD armor/MR is wiki prose. Buffs are
  emitted as ``stat_buff`` so items and the stats panel see them;
  nothing in her own kit scales off them at parse time (no apply_to).
"""

import math
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import (
    AbilityAtomQuery,
    atom_receipt,
    ranked_ability_atom_value,
    required_ability_atom,
)
from ..ability_spec import AttackClass, ControlEvent, DamageClass, DamagePart
from ..binary_roots import data_value, spell_object
from ..survival.actions import TransitionRank
from .engine import BUFF, DEBUFF, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat, float_option, int_option, target_stat
from .module_helpers import missing_hp_fraction
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)
from .source_receipts import load_champion_sources

# The P/Q/R effect records carry the duration, stack, and ratio values; the
# level-banded bleed base and bonus-AD ratio remain prose/leveling-backed.
# https://wiki.leagueoflegends.com/en-us/Briar
P_BLEED_BASE_MIN = 10.0  # single-stack total at level 1
P_BLEED_BASE_MAX = 50.0  # single-stack total at level 18
P_BLEED_LEVEL_CAP = 18  # wiki defines levels 1-18; clamp past that
P_BLEED_BONUS_AD_RATIO = 0.5  # + 50% bonus AD per stack
_BRIAR_P_SPELL = spell_object("Briar", "BriarP")
_BRIAR_Q_SPELL = spell_object("Briar", "BriarQ")
_BRIAR_R_SPELL = spell_object("Briar", "BriarR")
P_BLEED_DURATION = data_value(_BRIAR_P_SPELL, "BleedDuration")
P_BLEED_MAX_STACKS = int(data_value(_BRIAR_P_SPELL, "MaxBleedStacks"))
P_BLEED_EXTRA_STACK_EFFECTIVENESS = data_value(
    _BRIAR_P_SPELL, "BleedPercentAdd"
)  # stacks beyond the first
R_RESIST_PER_TOTAL_AD = data_value(_BRIAR_R_SPELL, "ResistADRatio")


# Head Rush shreds "for 5 seconds" — not the rest of the fight.
Q_SHRED_DURATION = data_value(_BRIAR_Q_SPELL, "ShredDuration")

# This module always prices the fully-charged scream ("Maximum Magic
# Damage"), and the cache says how long that charge takes: Briar "prepares
# to unleash a scream in the target direction, charging for up to 1 second"
# and "Chilling Scream can be recast within the duration, and does so
# automatically afterwards" (data/champions.json Briar E).  A full charge
# is therefore the whole cached second, and the scream lands at its end.
# The charge's own healing stays inside the charge: it is declared
# ``HealAnchor.CAST_SCHEDULE`` and counts its four 0.25-second ticks from
# the cast, not from the damage the scream eventually deals.
E_FULL_CHARGE_SECONDS = 1.0


def _crimson_curse(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: declare the stacking bleed; damage.py walks the hit timeline.

    Single stack = 10-50 by level (linear over 1-18, clamped past 18)
    + 50% bonus AD, physical over 5s. Cross-check: the JSON's 5-stack
    window totals (P effect[0].leveling[4]) are exactly 2x this base.
    """
    ability = ctx.ability()
    if ability is None:
        return None

    level = min(ctx.level, P_BLEED_LEVEL_CAP)
    single_stack = (
        P_BLEED_BASE_MIN
        + (P_BLEED_BASE_MAX - P_BLEED_BASE_MIN) * (level - 1) / 17.0
        + P_BLEED_BONUS_AD_RATIO * ctx.stat("bonus_attack_damage")
    )
    name = ability_name(ability)
    return {
        "name": name,
        "damage_type": "physical",
        "total_raw": single_stack,
        "parts": (),
        "stacking_dot": {
            "name": f"{name} (bleed)",
            "damage_type": "physical",
            "single_stack_raw": single_stack,
            "duration": P_BLEED_DURATION,
            "max_stacks": P_BLEED_MAX_STACKS,
            "extra_stack_effectiveness": P_BLEED_EXTRA_STACK_EFFECTIVENESS,
            "applied_by_autos": True,
            # The ingested ability description specifies 0.5-second ticks.
            "tick_interval": 0.5,
        },
    }


def _head_rush(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: physical hit + item on-hit application + armor/MR shred."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
        # The leap lands one hit on the target it leaps to.
        event_order_certified="single_hit",
    )
    # Q is a real attack (wiki data template): per-hit on-hit items at
    # 100%, shared Kraken/Hullbreaker counter, on-attack cadences
    # (Guinsoo phantom counter). Spellblade stays with the next auto.
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit", "on_attack"),
    }
    entry["applies_dot_stack"] = True
    shred = extract_value(ability, "Resistances Reduction", rank)
    if shred > 0:
        # damage.py applies the shred AFTER Q's own damage, so only
        # later casts in the rotation benefit (the Kog'Maw rule).
        entry["target_debuff"] = {
            "armor_reduction_percent": shred,
            "mr_reduction_percent": shred,
            "duration": Q_SHRED_DURATION,
        }
    return entry


_head_rush.phase = DEBUFF


def _blood_frenzy(ctx: SlotCtx) -> dict[str, Any] | None:
    """W buff: +attack speed / +move speed while the frenzy is active.

    The cleave (60-100% AD around the target) is skipped entirely — it
    never hits the primary target. Off-toggle drops the whole slot.
    """
    if not ctx.option("blood_frenzy_active"):
        return None
    ranked = ctx.ranked("W", 0)
    if ranked is None:
        return None
    ability, rank = ranked

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    entry["stat_buff"] = {
        "bonus_attack_speed": extract_value(ability, "Bonus Attack Speed", rank),
        "movement_speed_percent": extract_value(ability, "Bonus Movement Speed", rank),
    }
    return entry


_blood_frenzy.phase = BUFF


def _snack_attack(ctx: SlotCtx) -> dict[str, Any] | None:
    """W cast row: Snack Attack, the frenzy's empowered next basic attack.

    Bonus physical damage = 5-65 + 5% AD + [9% + 2.5% per 100 bonus AD]
    of the target's MISSING health — the compound unit resolves against
    a target context whose missing health comes from the shared
    ``target_missing_hp_pct`` option. Fires exactly once per W cast
    (empowers_next_auto: the swing is one of the fight's autos, which
    already applies item on-hits; one-rotation mode appends the
    consumed base swing to this row).
    """
    if not ctx.option("blood_frenzy_active"):
        return None
    ability = ctx.ability("W", 1)
    frenzy = ctx.ability("W", 0)
    if ability is None or frenzy is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    target = dict(ctx.target or {})
    target["target_missing_health"] = target_stat(
        target, "target_max_health"
    ) * missing_hp_fraction(ctx)
    bonus = extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, target)

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(frenzy, rank),  # W[1] has no cooldown of its own
        bonus,
        "physical",
        # One empowered bite, riding the attack it empowers.
        event_order_certified="single_hit",
    )
    entry["empowers_next_auto"] = True
    entry["applies_dot_stack"] = True
    return entry


_E_REDUCTION_SOURCE = "Briar.E[0].effects[0].description"
_E_CONTROL_SOURCE = "Briar.E[0].effects[3].description"


def _chilling_scream(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: fully-charged magic damage, wall bonus, and the sourced
    charge-window damage reduction + terrain-collision control.

    JSON cross-check: "Total Magic Damage" == Maximum + Bonus, so the
    wall toggle is implemented as an addend on the Maximum read.

    While charging (``e_charge_seconds``, capped at the sourced 1s
    active duration) Briar takes 35% less damage from all sources: the
    typed damage-reduction atom prices the multiplier (1 - 35/100) and
    the active-duration atom prices the window.  The self-state packet
    carries both atom receipts.  With ``e_wall_collision`` selected,
    the terrain-collision control sequence atom prices the knockup and
    stun that land on the primary target (control-only events, like the
    other reviewed control packets).
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    total = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    if ctx.option("e_wall_collision"):
        total += extract_named(
            ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target
        )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    # One scream, at the end of the charge this module always prices in
    # full, and it always knocks back there ("If Chilling Scream was
    # charged for its full duration, enemies hit are also knocked back 575
    # units"); the same hit also slows, but the knockback is the
    # immobilize a control-armed holder reads.
    entry["parts"] = (
        DamagePart(
            "magic",
            total,
            time_offset=E_FULL_CHARGE_SECONDS,
        ),
    )
    entry["event_order_certified"] = "single_hit"
    entry["applies_dot_stack"] = True

    # The atom catalog validates the same champion shape the pipeline parses.
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    reduction_atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source=_E_REDUCTION_SOURCE,
            behavior="ability",
            evidence_prefix="damage reduction@",
        ),
    )
    if [str(unit).strip().lower() for unit in reduction_atom["units"]] != ["%"]:
        raise ValueError("Briar E damage-reduction atom must use percent")
    reduction_percent = ranked_ability_atom_value(
        reduction_atom, 1, source=_E_REDUCTION_SOURCE
    )
    duration_atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source=_E_REDUCTION_SOURCE,
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if [str(unit).strip().lower() for unit in duration_atom["units"]] != ["s"]:
        raise ValueError("Briar E active-duration atom must use seconds")
    sourced_duration = ranked_ability_atom_value(
        duration_atom, 1, source=_E_REDUCTION_SOURCE
    )
    charge_seconds = min(
        max(float(ctx.option("e_charge_seconds")), 0.0),
        sourced_duration,
    )
    if charge_seconds > 0.0:
        entry["self_state_events"] = [
            {
                "kind": "damage_modifier",
                # 35% damage reduction -> take 65% of each incoming packet.
                "multiplier": 1.0 - reduction_percent / 100.0,
                "duration": charge_seconds,
                "source": f"{ability_name(ability)} · damage reduction",
                "source_atoms": [
                    atom_receipt(reduction_atom),
                    atom_receipt(duration_atom),
                ],
                # The reduction covers every damage type Briar takes while
                # charging (physical, magic, and true — the sourced prose
                # names no carve-out), so the modifier gates no source kind.
                "all_sources": True,
                # D-04: a modifier names its classes; "every damage type"
                # is the full declaration, never an empty one.
                "damage_classes": frozenset(DamageClass),
                "attack_classes": frozenset(AttackClass),
                # An amplification already in force at its own
                # timestamp, so it must price the hit landing at that
                # timestamp: that slot is AURA_ARM, and it is what
                # DEBUFF_ARM (a debuff some trigger armed) is not.
                "_rank": TransitionRank.AURA_ARM,
            }
        ]

    if ctx.option("e_wall_collision"):
        control_atom = required_ability_atom(
            ctx.champion_name,
            champion_data,
            "E",
            query=AbilityAtomQuery(
                source=_E_CONTROL_SOURCE,
                behavior="timing",
                evidence_prefix="control duration sequence@",
            ),
        )
        values = control_atom["values"]
        units = [str(unit).strip().lower() for unit in control_atom["units"]]
        if len(values) != 2 or units != ["s", "s"]:
            raise ValueError(
                "Briar E control duration sequence atom must carry knockup "
                "and stun seconds"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in values
        ):
            raise TypeError("Briar E control duration sequence atom must be numeric")
        knockup_seconds, stun_seconds = (float(values[0]), float(values[1]))
        if knockup_seconds <= 0.0 or stun_seconds <= 0.0:
            raise ValueError("Briar E control durations must be positive")
        # The rebound happens where the scream lands, which is the end of
        # the charge this module always prices in full — the same instant
        # the damage part carries.
        entry["control_events"] = (
            ControlEvent("knockup", knockup_seconds, time_offset=E_FULL_CHARGE_SECONDS),
            # The stun starts when the knockup ends (the sourced sequence
            # "knocked up for 0.5 seconds and stunned for 1.5 seconds").
            ControlEvent(
                "stun",
                stun_seconds,
                time_offset=E_FULL_CHARGE_SECONDS + knockup_seconds,
            ),
        )
        entry["control_source_atoms"] = [atom_receipt(control_atom)]
    return entry


def _certain_death(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: explosion magic damage + armor/MR/life-steal/move-speed buffs.

    The explosion is counted once, against the primary target. The
    dash/bite deals no additional damage (verified). Hematomania also
    re-triggers Blood Frenzy — covered by the ``blood_frenzy_active``
    toggle's default.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        # One explosion on arrival; the cached text gives the dash no
        # duration of its own to author as an offset.
        event_order_certified="single_hit",
    )
    entry["applies_dot_stack"] = True
    resist_bonus = R_RESIST_PER_TOTAL_AD * ctx.stat("attack_damage")
    entry["stat_buff"] = {
        "armor": resist_bonus,
        "magic_resistance": resist_bonus,
        "life_steal": extract_value(ability, "Life Steal", rank),
        "movement_speed_percent": extract_value(
            ability, "Additional Bonus Movement Speed", rank
        ),
    }
    return entry


_certain_death.phase = BUFF


OPTIONS: list[dict[str, Any]] = [
    bool_option(
        "blood_frenzy_active",
        True,
        label="Blood Frenzy / Hematomania frenzy active (W attack & move "
        "speed; enables Snack Attack; R maintains it)",
    ),
    bool_option(
        "e_wall_collision",
        False,
        label="E fully-charged knockback collides with terrain " "(bonus magic damage)",
    ),
    float_option(
        "e_charge_seconds",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="E charge seconds — the damage-reduction window while charging "
        "(35% less damage taken), capped at the sourced 1s active duration",
        rotation={"role": "self_state", "slot": "E"},
    ),
    int_option(
        "target_missing_hp_pct",
        50,
        minimum=0,
        maximum=100,
        label="Target missing health %",
    ),
]

ASSUMPTIONS = [
    "Self-heals modeled by healing.py (HEALING_RULE_CHAMPIONS): the "
    "bleed heals 25% of its pre-mitigation damage (Crimson Curse, "
    "cached prose 'always heals Briar for 25% of the pre-mitigation "
    "damage dealt'), Snack Attack heals 5% of maximum health + the "
    "sourced Heal Percentage (24-40%) of the bite's post-mitigation "
    "damage, and Certain Death's life steal (10/15/20%) heals from "
    "basic-attack damage while the frenzy lasts",
    "Bleed kill heal (125% of remaining bleed damage on kill) and the "
    "missing-health healing amplifier (0-40% + up to 2.5% per 100 "
    "bonus health) are death/live-state boundaries: the fight ends at "
    "the kill and the amplifier needs a live health walk, so both stay "
    "documented, not priced",
    "E's charge window is modeled: while charging for "
    "e_charge_seconds (default 1.0, capped at the sourced 1s active "
    "duration) Briar takes 35% less damage from all sources (the "
    "sourced damage-reduction atom prices the 0.65 multiplier and the "
    "active-duration atom prices the window, starting at the cast); "
    "the reduction applies to physical, magic, and true damage "
    "taken. E's charge heal IS modeled (healing.py, 4 sourced ticks)",
    "E wall collision (e_wall_collision): the fully-charged knockback "
    "rebound lands the sourced control duration sequence on the "
    "primary target — a 0.5s knockup followed by a 1.5s stun — "
    "creating target action downtime; both durations ride the one "
    "sequence atom receipt",
    "W cleave skipped — it hits only enemies around the primary target, "
    "contributing zero single-target damage; the cleave does not apply "
    "the bleed",
    "E assumed fully charged (uncharged base is 2-5.5)",
    "Q's attack-timer reset is not modeled as an extra auto",
    "Bleed cannot crit; bleed damage uses committed accounting — every "
    "stack applied during the fight counts its full 5s of ticks, "
    "including past fight end",
    "Bleed stacks come from autos and each damaging ability application "
    "(Q, Snack Attack, E, R); reapplying refreshes the shared duration",
    "R explosion counted once, against the primary target; fear/stun/"
    "slow CC not modeled",
    "Blood Frenzy assumed active by default (R's Hematomania re-triggers "
    "it for the whole ult); toggling it off also removes Snack Attack",
]

SLOTS = {
    "W_frenzy": _blood_frenzy,
    "R": _certain_death,
    "Q": _head_rush,
    "W": _snack_attack,
    "E": _chilling_scream,
    "P": _crimson_curse,
}

# Cached kit review.  Q "stuns them for 0.85 seconds"; W's Snack Attack
# bite and R's explosion apply nothing to the target they damage (R "fears
# all non-marked targets", and the marked one is the target it damages).
# E's scream now lands at the end of the cached charge and carries its
# knockback on the part itself (see ``_chilling_scream``), because that
# kind belongs to the full charge this module prices rather than to the
# slot.  W_frenzy and P emit no ability damage.
MODULE_CC = {"Q": "stun", "W": "none", "E": "knockback", "R": "none"}

parse_abilities = build_parser(SLOTS, "Briar", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Briar")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Briar self-healing events from its authored packet."""
    healing = []
    ability = _healing.ability_json(champion_data, "E")
    rank = _healing.parsed_rank(ability_damages, "E")
    per_tick = extract_named(ability, "Heal Per Tick", rank, champion_stats, {})
    maximum = extract_named(ability, "Maximum Heal", rank, champion_stats, {})
    if per_tick > 0.0 and maximum > 0.0:
        # The ticks are the charge's, not the scream's: Briar is "charging
        # for up to 1 second, during which she ... heals herself every 0.25
        # seconds" and only then unleashes the scream, so the cadence counts
        # from the CAST and stops before the damage the recast deals (cached
        # E, data/champions.json).  Nor is a tick caused by the scream's
        # damage — it happens while Briar is still charging, before there is
        # any — so the receipt carries no damage trigger.  Gating a 0.25s
        # tick on a hit that lands at 1.0s would drop three quarters of the
        # charge.  An E event is still what proves the cast happened; it is
        # not what the heal is paid for.
        for payment in _healing.payments(
            _healing.HealAnchor.CAST_SCHEDULE, "E", damage_events, cast_timeline
        ):
            ticks = max(1, min(4, math.ceil(maximum / per_tick)))
            healing.extend(
                {
                    "time": payment.cast_time + index * 0.25,
                    "amount": min(
                        float(per_tick),
                        max(0.0, maximum - per_tick * (index - 1)),
                    ),
                    "source": "Chilling Scream",
                    "kind": "champion_ability",
                }
                for index in range(1, ticks + 1)
            )
    # P (Crimson Curse) bleed self-heal: "The bleed always heals Briar
    # for 25% of the pre-mitigation damage dealt" (cached passive prose).
    # The bleed's own per-stack heal rows (2.5 : 12.5 + 12.5% bonus AD
    # per stack, +25% per extra-stack share) are exactly 25% of the
    # pre-mitigation bleed damage at every stack level, so one sourced
    # rule prices the whole stream.  The wiki's missing-health healing
    # amplifier (0% : 40%) is a live-state boundary, not priced here.
    for payment in _healing.payments(
        _healing.HealAnchor.DAMAGING_HIT,
        lambda source: source.startswith("stacking_dot_"),
        damage_events,
    ):
        event = payment.event
        dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
        amount = 0.25 * dealt
        if amount > 0.0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": amount,
                    "source": "Crimson Curse",
                    "kind": "champion_passive",
                    **_healing.trigger_fields(event),
                }
            )
    # W[1] (Snack Attack): "healing her for 5% of her maximum health
    # plus a percentage of the post-mitigation damage dealt" — the
    # percentage is the sourced "Heal Percentage" row (24 / 28 / 32 /
    # 36 / 40% by rank).  The heal pays once per activation, at the
    # bite's hit event; the CAST anchor keeps that one payment even if a
    # future W is priced as several hits.
    w_rank = _healing.parsed_rank(ability_damages, "W")
    heal_percent = extract_named(
        _healing.ability_json(champion_data, "W", 1),
        "Heal Percentage",
        w_rank,
        champion_stats,
        {},
    )
    max_health = champion_stat(champion_stats, "health")
    for payment in _healing.payments(
        _healing.HealAnchor.CAST, "W", damage_events, cast_timeline
    ):
        event = payment.event
        snack_heal = (
            0.05 * max_health
            + float(event.get("damage", 0.0) or 0.0) * heal_percent / 100.0
        )
        _healing.heal_from_damage(healing, event, snack_heal, "Snack Attack")
    # R (Certain Death) grants life steal (10 / 15 / 20% by rank) while
    # Hematomania lasts; life steal heals for the sourced percentage of
    # the post-mitigation damage dealt by basic attacks.
    r_rank = _healing.parsed_rank(ability_damages, "R")
    life_steal = extract_named(
        _healing.ability_json(champion_data, "R"),
        "Life Steal",
        r_rank,
        champion_stats,
        {},
    )
    if life_steal > 0.0:
        for payment in _healing.payments(
            _healing.HealAnchor.DAMAGING_HIT, "auto_attacks", damage_events
        ):
            event = payment.event
            _healing.heal_from_damage(
                healing,
                event,
                float(event.get("damage", 0.0) or 0.0) * life_steal / 100.0,
                "Certain Death",
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Briar")(derive_self_healing)
