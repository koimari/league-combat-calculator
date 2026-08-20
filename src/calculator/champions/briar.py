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

from typing import Any

from ..ability_spec import DamagePart
from .inputs import target_stat
from .engine import BUFF, DEBUFF, SlotCtx, build_parser
from .module_helpers import missing_hp_fraction
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value

# HARDCODED: verify on patch updates — wiki values with no clean JSON
# home (the P parse is degraded; R's resist buff is prose only).
# https://wiki.leagueoflegends.com/en-us/Briar
P_BLEED_BASE_MIN = 10.0  # single-stack total at level 1
P_BLEED_BASE_MAX = 50.0  # single-stack total at level 18
P_BLEED_LEVEL_CAP = 18  # wiki defines levels 1-18; clamp past that
P_BLEED_BONUS_AD_RATIO = 0.5  # + 50% bonus AD per stack
P_BLEED_DURATION = 5.0  # seconds per (refreshing) stack window
P_BLEED_MAX_STACKS = 5
P_BLEED_EXTRA_STACK_EFFECTIVENESS = 0.25  # stacks beyond the first
R_RESIST_PER_TOTAL_AD = 0.20  # armor AND MR gained, as % of total AD


# Head Rush shreds "for 5 seconds" — not the rest of the fight.
Q_SHRED_DURATION = 5.0

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
    name = ability.get("name", "Crimson Curse")
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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Head Rush"),
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
    if not ctx.options.get("blood_frenzy_active", True):
        return None
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    entry = damage_entry(
        ability.get("name", "Blood Frenzy"),
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
    if not ctx.options.get("blood_frenzy_active", True):
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
        ability.get("name", "Snack Attack"),
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


def _chilling_scream(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: fully-charged magic damage, plus the wall-collision bonus.

    JSON cross-check: "Total Magic Damage" == Maximum + Bonus, so the
    wall toggle is implemented as an addend on the Maximum read.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    if ctx.options.get("e_wall_collision", False):
        total += extract_named(
            ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target
        )
    entry = damage_entry(
        ability.get("name", "Chilling Scream"),
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
            cc_kind="knockback",
        ),
    )
    entry["event_order_certified"] = "single_hit"
    entry["applies_dot_stack"] = True
    return entry


def _certain_death(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: explosion magic damage + armor/MR/life-steal/move-speed buffs.

    The explosion is counted once, against the primary target. The
    dash/bite deals no additional damage (verified). Hematomania also
    re-triggers Blood Frenzy — covered by the ``blood_frenzy_active``
    toggle's default.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Certain Death"),
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
    {
        "key": "blood_frenzy_active",
        "type": "bool",
        "default": True,
        "label": (
            "Blood Frenzy / Hematomania frenzy active (W attack & move "
            "speed; enables Snack Attack; R maintains it)"
        ),
    },
    {
        "key": "e_wall_collision",
        "type": "bool",
        "default": False,
        "label": (
            "E fully-charged knockback collides with terrain " "(bonus magic damage)"
        ),
    },
    {
        "key": "target_missing_hp_pct",
        "type": "int",
        "default": 50,
        "min": 0,
        "max": 100,
        "label": "Target missing health %",
    },
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
    "E's 35% damage reduction while charging is not modeled — it "
    "reduces damage Briar TAKES during the ~1s channel, and the "
    "outgoing-damage packet model has no per-cast incoming-damage "
    "window (the Amumu E passive precedent); E's charge heal IS "
    "modeled (healing.py, 4 sourced ticks)",
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
MODULE_CC = {"Q": "stun", "W": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Briar", cc_kinds=MODULE_CC)


SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Briar",
        "revision_id": 4046069,
        "revision_timestamp": "2026-07-27T13:03:08Z",
    }
]

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Briar")
