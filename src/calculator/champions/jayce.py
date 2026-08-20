"""Jayce — slot map for the archetype engine.

Jayce is a two-form champion (the Gnar shape) with one extra twist that
breaks the engine's shared assumptions: he **starts with R at rank 1 and
can never level it**, so his 18 skill points all go to Q/W/E, which have
SIX ranks each. ``skill_orders._SKILL_ORDERS["Jayce"]`` therefore holds
no "R" at all, and ``get_ability_rank("R", ...)`` returns 0 for him —
the R slot below ignores rank entirely and keys its values off CHAMPION
LEVEL, which is where they genuinely scale.

Why each slot is non-generic:
- The ``hammer_stance`` option (off = Cannon, Jayce's default form)
  swaps which JSON entry every slot reads — a bool, like Gnar's
  ``mega``. Q/W/E store [0] = Hammer, [1] = Cannon; R
  stores the two INVERTED, so R resolves its entry by NAME. The forms
  emit genuinely different entry shapes (Hammer W is a 4-tick DoT,
  Cannon W an empowered-auto set; Hammer E is %maxHP damage, Cannon E a
  non-damaging enabler), so each slot is a small champion-local form
  dispatcher rather than a ``by_option`` (whose cases must share a
  shape).
- Q Cannon (Shock Blast) picks its attribute by the ``accelerated_q``
  option: "Increased Damage" is the TOTAL of a blast fired through the
  Acceleration Gate (exactly 1.4x the base "Physical Damage" line at
  every rank), never an addition to it — reading both would overstate Q
  by 240%. Q Hammer is a plain read whose "Slow" entry must not leak.
- W Hammer (Lightning Field) must read "Total Magic Damage" by exact
  name: the ability's FIRST leveling entry is "Mana Restored", a
  resource restore, and its second is the per-tick line (the total is
  exactly 4x it — 4 ticks over 4 seconds, declared as ``dot_duration``
  so item burns keep refreshing through the zone).
- W Cannon (Hyper Charge) empowers the next 3 basic attacks to deal
  MODIFIED physical damage — 70-110% of TOTAL AD REPLACES the attack's
  own damage rather than adding to it, so at rank 1 each empowered
  attack hits for LESS than a plain auto. The entry therefore carries
  only the DELTA from a normal swing and rides ``empowers_next_auto``
  (see ``_hyper_charge``). Its +360% bonus attack speed and 3-attack
  window have no JSON home and live as constants. The speed belongs to
  those 3 attacks ONLY — declared as ``empowers_next_auto``'s
  ``attack_speed`` rather than a fight-wide ``stat_buff``, because the
  buff ends when its third attack lands. The fight engine spends the
  burst at that rate and runs the rest of the fight at Jayce's ordinary
  one, so W buys extra ordinary autos with the time it saves.
- E Hammer (Thundering Blow) is MAGIC damage despite scaling off bonus
  AD; its one "Magic Damage" leveling entry carries BOTH the %maxHP and
  the bonus-AD modifier, and its "Capped Monster Damage" sibling entry
  is a monster-only clamp that must never reach a champion target.
  E Cannon (Acceleration Gate) is a pure movement-speed zone — absent
  from the results; its only damage relevance is supercharging Shock
  Blast, which ``accelerated_q`` owns.
- R (Transform) has ENTIRELY EMPTY ``leveling`` arrays in both JSON
  entries: every number is module constants (below). Hammer grants
  armor+MR and one empowered magic auto; Cannon shreds the target's
  armor+MR as a ``target_debuff`` (the Kog'Maw rule: applied after the
  ability's own damage, so it never amplifies itself) and raises attack
  range from 125 to 500 — a range change with no damage effect, noted
  here and modeled nowhere.
- P (Hextech Capacitor) grants movement speed and ghosting on stance
  swap. No damage, no damage-relevant stat — absent from the map. Its
  two JSON entries ("Hextech Capacitor" / "Hextech Capacitor 2") carry
  byte-identical descriptions and are a parser artifact, not two
  effects.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..stats import ATTACK_SPEED_CAP
from .engine import SlotCtx, build_parser
from .slotlib import (
    by_option,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — against the GAME FILES, not the
# wiki (a stale wiki transform box is exactly what burned Gnar):
# https://raw.communitydragon.org/latest/game/data/characters/jayce/jayce.bin.json
# Both R entries have empty ``leveling`` arrays, so every value here
# lives only in tooltip prose. The game file states them as level
# breakpoints under
# Spells/JayceStanceHtGAbility/JayceStanceHtG/mSpell/mSpellCalculations:
#   Resists         mLevel1Value 5.0,  +7.0  at levels 6/11/16
#                   + 7.5% of bonus AD (StatByCoefficient, bonus-only)
#   Damage          mLevel1Value 25.0, +35.0 at levels 6/11/16
#                   + ADRatio 0.30 of bonus AD
#   RangedFormShred mLevel1Value 0.20, +0.05 at levels 6/11/16
# Each tuple below is indexed by ``_level_tier``.
TRANSFORM_BREAKPOINTS = (6, 11, 16)
HAMMER_BONUS_RESISTS = (5.0, 12.0, 19.0, 26.0)
HAMMER_RESISTS_BONUS_AD_RATIO = 0.075
HAMMER_EMPOWERED_AUTO_DAMAGE = (25.0, 60.0, 95.0, 130.0)
HAMMER_EMPOWERED_AUTO_BONUS_AD_RATIO = 0.30
CANNON_SHRED_PERCENT = (20.0, 25.0, 30.0, 35.0)
CANNON_SHRED_DURATION = 5.0

# HARDCODED: Hyper Charge's steroid and attack count have no JSON
# leveling entry (only the per-attack AD ratio does). Same game file,
# Spells/JayceHyperChargeAbility/JayceHyperCharge/mSpell/DataValues:
# PercentIncreasedAS 3.6 (i.e. +360%, flat at all ranks), NumAttacks 3.
HYPER_CHARGE_BONUS_ATTACK_SPEED = 360.0
HYPER_CHARGE_ATTACKS = 3

# Lightning Field ticks once a second for 4 seconds (wiki prose; the
# JSON's per-tick line is exactly a quarter of the total it reads).
LIGHTNING_FIELD_DURATION = 4.0

# R is never leveled: it is permanently rank 1.
_TRANSFORM_RANK = 1

# Q/W/E JSON entry order. R's is inverted — ``_transform_ability``
# resolves that slot by name instead.
_HAMMER, _CANNON = 0, 1

# Substring identifying each stance's R entry by name.
_TRANSFORM_NAMES = {"hammer": "Mercury Hammer", "cannon": "Mercury Cannon"}


def _is_hammer(ctx: SlotCtx) -> bool:
    """True in Hammer stance; Cannon (Jayce's default form) is False."""
    return bool(ctx.options.get("hammer_stance", False))


def _level_tier(level: int) -> int:
    """Index into R's per-level tables: 0 for 1-5, 1 for 6-10, 2 for
    11-15, 3 for 16+ — R's values step at champion level, not rank."""
    return sum(1 for breakpoint in TRANSFORM_BREAKPOINTS if level >= breakpoint)


# ---------------------------------------------------------------------------
# Q: To the Skies! (Hammer) / Shock Blast (Cannon)
# ---------------------------------------------------------------------------


# Every kind below rides its own construction rather than MODULE_CC: each
# Jayce slot is a stance dispatcher, and the two stances' abilities are
# different spells with different control.
_q_hammer = simple_damage(
    attr="Physical Damage",
    dmg_type="physical",
    source=("Q", _HAMMER),
    # "smashes his hammer to the ground to deal physical damage ...
    # and slow them for 2 seconds"
    cc_kind="slow",
    event_order_certified="single_hit",
)

# Cannon's two cases DO share one entry shape, so the gate is a plain
# ``by_option``: gated Shock Blast reads the "Increased Damage" TOTAL,
# ungated reads the base line.
_q_cannon = by_option(
    "accelerated_q",
    {
        # Shock Blast only detonates and grants sight — no control.
        True: simple_damage(
            attr="Increased Damage",
            dmg_type="physical",
            source=("Q", _CANNON),
            cc_kind="none",
            event_order_certified="single_hit",
        ),
        False: simple_damage(
            attr="Physical Damage",
            dmg_type="physical",
            source=("Q", _CANNON),
            cc_kind="none",
            event_order_certified="single_hit",
        ),
    },
    default=True,
)


def _q(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: To the Skies! (Hammer) or Shock Blast (Cannon, gate-aware)."""
    return _q_hammer(ctx) if _is_hammer(ctx) else _q_cannon(ctx)


# ---------------------------------------------------------------------------
# W: Lightning Field (Hammer) / Hyper Charge (Cannon)
# ---------------------------------------------------------------------------


def _w_hammer(ctx: SlotCtx) -> dict[str, Any] | None:
    """W Hammer: Lightning Field's 4 sourced ticks of the full-zone total.

    The JSON's "Total Magic Damage" is exactly 4x the "Magic Damage Per
    Tick" row at every rank (140/35 .. 440/110), so the field is priced
    as four per-second ticks over its 4-second duration.
    """
    ability = ctx.ability("W", _HAMMER)
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Lightning Field"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    ticks = int(LIGHTNING_FIELD_DURATION)
    entry["parts"] = (
        DamagePart(
            "magic",
            total / ticks,
            count=ticks,
            time_offset=1.0,
            hit_interval=1.0,
            # The field only "deals magic damage every second".
            cc_kind="none",
        ),
    )
    # Item burns (Liandry's, Blackfire Torch) stay refreshed through the
    # whole 4-second field (the Cassiopeia rule).
    entry["dot_duration"] = LIGHTNING_FIELD_DURATION
    return entry


def _burst_attack_speed(ctx: SlotCtx) -> float:
    """Attacks per second while Hyper Charge's 3 attacks are firing.

    "Maximum Attack Speed" in the in-game tooltip: +360% on Jayce's 0.658
    ratio reaches 3.027, just past the game's 3.003 clamp, so the burst
    sits AT the cap for any build. Bonus attack speed from items is
    therefore wasted during the burst — it only speeds his ordinary autos.
    """
    attack_speed = ctx.stat("attack_speed")
    as_ratio = ctx.stat("attack_speed_ratio")
    burst = attack_speed + as_ratio * (HYPER_CHARGE_BONUS_ATTACK_SPEED / 100.0)
    return min(burst, ATTACK_SPEED_CAP)


def _hyper_charge(ctx: SlotCtx) -> dict[str, Any] | None:
    """W Cannon: 3 attacks whose AD ratio REPLACES the auto's own damage.

    The wiki's "modified physical damage" is a replacement, not a bonus:
    each empowered attack deals ``ratio x total AD`` INSTEAD of its
    normal swing, so at rank 1 (70%) it is a downgrade and only from
    rank 5 a per-hit gain. The entry therefore carries the DELTA from a
    normal swing (negative at low ranks) and declares
    ``empowers_next_auto``, which makes both fight modes come out at
    ``3 x ratio x total AD``:
      - with an auto stream, the three attacks ARE three of the fight's
        autos (item on-hits at full effectiveness on the same shared
        counter sequence as any other auto) and the delta adjusts them;
      - with none, the engine appends its own three 100%-AD swings to
        this row and the same delta adjusts those.
    The attacks crit normally ("Hyper Charge's total damage is affected
    by critical strike modifiers"), so the delta crits with them.
    """
    ability = ctx.ability("W", _CANNON)
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    ratio = extract_value(ability, "Physical Damage", rank) / 100.0
    total_ad = ctx.stat("attack_damage")
    delta_ratio = ratio - 1.0
    return {
        "name": ability.get("name", "Hyper Charge"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        # Diagnostic: what the three attacks are worth IN TOTAL (the
        # number the tooltip describes), not the parts sum — the parts
        # deliberately hold only the delta from the swings they modify.
        "total_raw": ratio * total_ad * HYPER_CHARGE_ATTACKS,
        "parts": (
            DamagePart(
                "physical",
                delta_ratio * total_ad,
                count=HYPER_CHARGE_ATTACKS,
                crit_effectiveness=1.0,
                basic_damage=True,
                bonus_ad_ratio=delta_ratio,
                # Hyper Charge only "empowers his next 3 basic attacks
                # ... to deal modified physical damage and gain 360%
                # bonus attack speed" — no control on the swings it
                # forces, which is what this row's events are.
                cc_kind="none",
            ),
        ),
        "empowers_next_auto": {
            "hits": HYPER_CHARGE_ATTACKS,
            "attack_speed": _burst_attack_speed(ctx),
            # Pressing W does not start the timer — spending the third
            # attack does, so the burst's own ~1s precedes the cooldown
            # (and cannot Navori-refund it).
            "cooldown_starts_after_hits": True,
        },
    }


def _w(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Lightning Field (Hammer) or Hyper Charge (Cannon) by stance."""
    return _w_hammer(ctx) if _is_hammer(ctx) else _hyper_charge(ctx)


# ---------------------------------------------------------------------------
# E: Thundering Blow (Hammer) / Acceleration Gate (Cannon — no damage)
# ---------------------------------------------------------------------------

_e_hammer = simple_damage(
    attr="Magic Damage",
    dmg_type="magic",
    source=("E", _HAMMER),
    # The root lands over the cast time; what arrives with the damage
    # is the "knock them back 600 units".
    cc_kind="knockback",
    event_order_certified="single_hit",
)


def _e(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Thundering Blow (Hammer); Cannon's gate emits nothing."""
    return _e_hammer(ctx) if _is_hammer(ctx) else None


# ---------------------------------------------------------------------------
# R: Transform — no rank, module constants, values step with level
# ---------------------------------------------------------------------------


def _transform_ability(ctx: SlotCtx, stance: str) -> dict[str, Any] | None:
    """R's JSON entry for a stance, resolved BY NAME.

    R's entries are ordered [0] = Cannon, [1] = Hammer — inverted
    relative to Q/W/E's [0] = Hammer. Matching the name keeps a data
    re-pull that reorders them from silently swapping the two forms.
    """
    needle = _TRANSFORM_NAMES[stance]
    for index in range(len(ctx.abilities.get("R", []))):
        ability = ctx.ability("R", index)
        if ability is not None and needle in ability.get("name", ""):
            return ability
    return None


def _transform_hammer(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any]:
    """R Hammer: armor/MR buff + ONE empowered bonus-magic basic attack."""
    tier = _level_tier(ctx.level)
    bonus_ad = ctx.stat("bonus_attack_damage")
    resists = HAMMER_BONUS_RESISTS[tier] + HAMMER_RESISTS_BONUS_AD_RATIO * bonus_ad
    bonus_damage = (
        HAMMER_EMPOWERED_AUTO_DAMAGE[tier]
        + HAMMER_EMPOWERED_AUTO_BONUS_AD_RATIO * bonus_ad
    )
    entry = damage_entry(
        ability.get("name", "Transform Mercury Hammer"),
        _TRANSFORM_RANK,
        extract_cooldown(ability, _TRANSFORM_RANK),
        bonus_damage,
        "magic",
        # The transform empowers one attack with bonus magic damage and
        # buffs Jayce; nothing lands on the target but damage.
        cc_kind="none",
        event_order_certified="single_hit",
    )
    # Self-defensive only — shown in the stats panel, no effect on
    # outgoing damage.
    entry["stat_buff"] = {"armor": resists, "magic_resistance": resists}
    # "Empowers his next basic attack" — once per transform, not per auto.
    entry["empowers_next_auto"] = True
    return entry


def _transform_cannon(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any]:
    """R Cannon: ONE empowered attack shredding armor/MR; no damage."""
    shred = CANNON_SHRED_PERCENT[_level_tier(ctx.level)]
    entry = damage_entry(
        ability.get("name", "Transform Mercury Cannon"),
        _TRANSFORM_RANK,
        extract_cooldown(ability, _TRANSFORM_RANK),
        0.0,
        "physical",
    )
    # The engine applies a target_debuff AFTER the ability's own damage,
    # so the shred can never amplify the attack that applied it.
    entry["target_debuff"] = {
        "armor_reduction_percent": shred,
        "mr_reduction_percent": shred,
        "duration": CANNON_SHRED_DURATION,
    }
    entry["detail"] = (
        f"No direct damage — the next basic attack reduces the target's "
        f"armor and magic resist by {shred:g}% for 5s"
    )
    return entry


def _transform(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: form-picked Transform, keyed off LEVEL because it has no rank.

    Jayce starts with R and never levels it, so the skill order reports
    rank 0 — this slot must not gate on it. Its values genuinely scale
    with champion level (tiers at 1/6/11/16), which ``_level_tier``
    resolves.
    """
    stance = "hammer" if _is_hammer(ctx) else "cannon"
    ability = _transform_ability(ctx, stance)
    if ability is None:
        return None
    if stance == "hammer":
        return _transform_hammer(ctx, ability)
    return _transform_cannon(ctx, ability)


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "hammer_stance",
        "type": "bool",
        "default": False,
        "label": "Hammer stance (Cannon when off)",
    },
    {
        "key": "accelerated_q",
        "type": "bool",
        "default": True,
        "label": "Shock Blast through Acceleration Gate (+40%)",
    },
]

# Jayce transforms INTO a stance and only then uses its abilities, so R
# resolves FIRST — the engine's default puts it last, where Cannon R's
# armor/MR shred would reach the autos but none of the Q/W it precedes.
CAST_ORDER = ["R", "Q", "Q2", "W", "E"]

ASSUMPTIONS = [
    "Jayce is modeled in ONE stance at a time — toggle hammer_stance to "
    "see each form. The cross-stance burst combo (gate -> supercharged "
    "Shock Blast -> Transform -> empowered Hammer auto -> Thundering Blow "
    "-> To the Skies!) is not modeled as a single rotation",
    "R (Transform) values are module constants from the live game files: "
    "both JSON entries have empty leveling arrays. They step with "
    "CHAMPION LEVEL at 1/6/11/16, not with rank — R starts at rank 1 and "
    "is never leveled, which is also why Q/W/E have six ranks",
    "R's empowered basic attack applies ONCE per transform, not on every auto",
    "Hammer R's bonus armor and magic resist appear in the champion stats "
    "panel but have no effect on outgoing damage",
    "Cannon R's armor/MR shred applies only to damage dealt after the "
    "empowered attack lands. Jayce transforms BEFORE he casts, so R "
    "resolves first and the shred reaches the Q/W of the combo it opens",
    "R's shred lasts 5s. In a timed fight longer than that it has worn "
    "off before the later casts, so it is applied weighted by the share "
    "of the fight it is actually up (a 10s fight gets half of it). A "
    "one-rotation burst always gets the full shred",
    "Hyper Charge's 3 attacks deal MODIFIED damage — the basic attack's "
    "own damage is replaced by 70-110% of total AD, not supplemented. "
    "They crit normally and apply item on-hits at full effectiveness on "
    "the fight's shared hit sequence",
    "Hyper Charge's attack speed applies to its 3 attacks only, not the "
    "whole fight: they fire at the game's 3.003 cap (which +360% on "
    "Jayce's ratio always reaches, hence the tooltip's 'maximum Attack "
    "Speed'), then autos resume at his ordinary rate. Bonus attack speed "
    "from items is wasted during the burst but still speeds his autos",
    "Hyper Charge's window is modeled by its 3 attacks, not its 4-second "
    "timer — the 3 attacks always land well inside 4 seconds",
    "Hyper Charge's cooldown starts when its 3rd attack is spent, not on "
    "cast (in-game behaviour), so its recast cycle is the burst's ~1s "
    "plus the cooldown. Those 3 attacks therefore cannot Navori-refund "
    "W's own cooldown — it is not running yet — though they do refund "
    "Jayce's other basic abilities",
    "Q's bonus damage against monsters, E's monster damage cap and W's "
    "mana restore are not modeled (the target is a champion)",
    "Cannon E (Acceleration Gate) emits nothing: its movement speed is "
    "utility and its Shock Blast supercharge is the accelerated_q option",
    "Cannon R raises attack range from 125 to 500; Jayce's JSON attackType "
    "is RANGED, so melee/ranged item scaling treats him as ranged in BOTH "
    "stances (matching the wiki's range-type classification)",
    "Passive (Hextech Capacitor) not modeled — movement speed and "
    "ghosting on stance swap only",
]

SLOTS = {
    "Q": _q,
    "W": _w,
    "E": _e,
    "R": _transform,
}

parse_abilities = build_parser(SLOTS, "Jayce")


SOURCES = load_champion_sources("Jayce")
