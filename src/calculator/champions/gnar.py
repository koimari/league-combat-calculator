"""Gnar — slot map for the archetype engine.

Why each slot is non-generic:
- Gnar's two forms live as paired JSON entries per slot (Q[0]/Q[1],
  W[0]/W[1], E[0]/E[1]); the ``mega`` option swaps which entry every
  slot reads. The forms emit different entry shapes (Mini W is an
  on-hit shell, Mega W a cast; Mini E carries a stat_buff, Mega E does
  not), so each slot is a small champion-local form dispatcher rather
  than a ``by_option`` (whose cases must share one shape).
- P (Rage Gene) deals no damage, but Mega form grants stat bonuses
  that exist nowhere in the JSON (its ``leveling`` is empty) — module
  constants (from the Community Dragon game files; the wiki's Mega
  stat box is stale) applied as a BUFF-phase buff so E (%maxHP) and
  Q/W (%AD) parse against buffed stats, and echoed in ``stat_buff`` so
  the fight engine buffs autos and attack speed. The deltas are BASE
  stats — bonus AD stays 0 without items, which R's %bonus-AD ratios
  require (in-game confirmed: itemless R wall deals its flat base).
- Q (Boomerang Throw / Boulder Toss) is a plain "Physical Damage" read
  per form ("Reduced Damage" is the subsequent-target falloff — a
  single target is hit once at full damage), with the catch/pickup
  cooldown refund (wiki prose) applied via the ``q_pickup`` option.
- W Mini (Hyper) procs every 3rd basic attack (Vayne Silver Bolts
  shell); its single leveling entry sums THREE modifiers (flat +
  %target max HP + AP), which ``pct_health_per_hit`` cannot do, so the
  per-proc sum is a champion-local ``sum_modifiers``. W Mega (Wallop)
  is a plain read of W[1].
- E Mini (Hop) couples "Physical Damage" (6% of Gnar's own max HP)
  with the "Bonus Attack Speed" leveling as a stat_buff on the same
  entry. E Mega (Crunch) scales off "% of his maximum health" — a unit
  scaling.py does not know — resolved with a local modifier override
  against the (Mega-buffed) ``ctx.stats["health"]``.
- R (GNAR!) is Mega-only: Mini form emits nothing; Mega picks its
  attribute by the ``r_wall`` option ("Increased Damage" is the TOTAL
  wall-crash damage, 1.5x the normal, not additive).
"""

from typing import Any

from ..ability_spec import ControlEvent, DamagePart
from ..binary_roots import character_record_root, record_value
from ..stats import growth_stat
from .engine import BUFF, SlotCtx, build_parser
from .inputs import bool_option, int_option
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    by_option,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)
from .source_receipts import load_champion_sources

# ROOTED IN THE BINARIES: the five Mega deltas are computed at import as
# GnarBig's CharacterRecord root minus Mini Gnar's (both tracked under
# data/bin/characters/).  The wiki's Mega stat box is stale (claims 5.7
# AD growth; the game says 5.5 — confirmed by in-game testing), so the
# roots are the authority.  The AD counts as base AD, never bonus AD —
# R's %bonus-AD ratios see 0 without items.  Attack speed is a LOSS in
# percentage points of bonus attack speed (it cancels Mini's
# growth-derived bonus AS: 6%/level Mini vs 0.5%/level Mega).
_MINI_ROOT = character_record_root("Gnar")
_MEGA_ROOT = character_record_root("GnarBig")


def _mega_delta(base_field: str, growth_field: str) -> tuple[float, float]:
    """One (base, growth) delta, each term snapped back to authored digits."""
    base = float(
        f"{record_value(_MEGA_ROOT, base_field) - record_value(_MINI_ROOT, base_field):.6g}"
    )
    growth = float(
        f"{record_value(_MEGA_ROOT, growth_field) - record_value(_MINI_ROOT, growth_field):.6g}"
    )
    return (base, growth)


MEGA_BONUS_HEALTH = _mega_delta("baseHPModifiable", "hpPerLevelModifiable")
MEGA_BONUS_AD = _mega_delta("baseDamageModifiable", "damagePerLevelModifiable")
MEGA_BONUS_ARMOR = _mega_delta("baseArmorModifiable", "armorPerLevelModifiable")
MEGA_BONUS_MR = _mega_delta("baseMR", "mrPerLevel")
_ATTACK_SPEED_PER_LEVEL_DELTA = record_value(
    _MINI_ROOT, "attackSpeedPerLevelModifiable"
) - record_value(_MEGA_ROOT, "attackSpeedPerLevelModifiable")
MEGA_ATTACK_SPEED_LOSS = (0.0, float(f"{_ATTACK_SPEED_PER_LEVEL_DELTA:.6g}"))

# HARDCODED: catching Q refunds 40% (Mini) / 70% (Mega) of the
# cooldown (wiki prose) -> remaining-cooldown multiplier per form.
_Q_PICKUP_CD_MULT = (0.6, 0.3)

# Hyper procs on every 3rd basic attack (wiki prose, not JSON).
_HYPER_STACKS = 3

# Crunch's own-max-HP unit, unknown to scaling.py's shared unit table.
_CRUNCH_OWN_HP_UNIT = "% of his maximum health"


def _form_index(ctx: SlotCtx) -> int:
    """JSON entry index for the current form: 0 = Mini, 1 = Mega."""
    return 1 if ctx.option("mega") else 0


# ---------------------------------------------------------------------------
# P: Rage Gene — Mega form stat bonuses (BUFF phase)
# ---------------------------------------------------------------------------


def _rage_gene(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Mega form stat bonuses from module constants (BUFF phase).

    Mini form emits nothing (Rage Gene itself deals no damage). Mega
    form mutates ``ctx.stats`` so every damage slot parses against
    buffed stats — E's %maxHP after +health, R's %bonus AD after +AD —
    and emits the same deltas in ``stat_buff`` for the fight engine
    (autos see the AD buff; ``bonus_attack_speed`` applies the AS loss
    through the champion's AS ratio, so it is not mirrored into the
    parse stats, which no damage read consumes).
    """
    if _form_index(ctx) == 0:
        return None
    ability = ctx.ability()
    if ability is None:
        return None

    hp = growth_stat(*MEGA_BONUS_HEALTH, ctx.level)
    ad = growth_stat(*MEGA_BONUS_AD, ctx.level)
    armor = growth_stat(*MEGA_BONUS_ARMOR, ctx.level)
    mr = growth_stat(*MEGA_BONUS_MR, ctx.level)
    as_loss = growth_stat(*MEGA_ATTACK_SPEED_LOSS, ctx.level)

    # Base-stat deltas: AD lands in attack_damage/base_attack_damage
    # only — bonus_attack_damage must stay untouched (R scales %bonus AD).
    for key, value in (
        ("health", hp),
        ("base_health", hp),
        ("attack_damage", ad),
        ("base_attack_damage", ad),
        ("armor", armor),
        ("magic_resistance", mr),
    ):
        ctx.stats[key] = ctx.stat(key) + value

    entry = damage_entry(ability_name(ability), 0, 0.0, 0.0, "physical")
    entry["stat_buff"] = {
        "base_health": hp,
        "base_attack_damage": ad,
        "armor": armor,
        "magic_resistance": mr,
        "bonus_attack_speed": -as_loss,
    }
    return entry


_rage_gene.phase = BUFF


# ---------------------------------------------------------------------------
# Q: Boomerang Throw (Mini) / Boulder Toss (Mega)
# ---------------------------------------------------------------------------


def _boomerang_throw(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q Mini: primary hit plus return-pass hits at the sourced 50% row.

    The cached prose: the boomerang "deals physical damage to enemies
    in its path ... After reaching its maximum range or hitting an
    enemy, the boomerang flies back ... dealing 50% damage to
    subsequent enemies" — the "Reduced Damage" row is exactly 50% of
    "Physical Damage" at every rank.  Each ``q_secondary_targets``
    enemy hit on the return pass takes one reduced hit (enemies can be
    hit only once per pass, so the primary never double-dips).
    """
    ranked = ctx.ranked("Q", 0)
    if ranked is None:
        return None
    ability, rank = ranked

    primary = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    reduced = extract_named(ability, "Reduced Damage", rank, ctx.stats, ctx.target)
    secondary = min(max(int(ctx.option("q_secondary_targets")), 0), 5)
    total = primary + reduced * secondary
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    if secondary:
        # The return pass lands on its own targets, one hit each, so the
        # row is timed rather than certified as one landing — the timing
        # is what carries Q's reviewed slow into the event ledger.
        parts = [
            DamagePart("physical", primary, time_offset=0.0),
            DamagePart(
                "physical", reduced, count=secondary, time_offset=0.0, hit_interval=0.0
            ),
        ]
        entry["detail"] = (
            f"primary hit + {secondary} return-pass target(s) at the "
            f"sourced {reduced / primary * 100:g}% Reduced Damage row each"
        )
    else:
        # One boomerang, one enemy: one part and one hit, the
        # certification that carries the same answer.
        parts = [DamagePart("physical", primary)]
        entry["event_order_certified"] = "single_hit"
    entry["parts"] = tuple(parts)
    return entry


_q_forms = (
    # Mini's boomerang states its own landing count (the return pass may
    # carry more than one); Mega's boulder "stops on the first enemy hit",
    # so its row is one part and one hit.
    _boomerang_throw,
    simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        source=("Q", 1),
        event_order_certified="single_hit",
    ),
)


def _q(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: form-picked "Physical Damage"; catching it refunds cooldown."""
    form = _form_index(ctx)
    entry = _q_forms[form](ctx)
    if entry is not None and ctx.option("q_pickup"):
        entry["cooldown"] *= _Q_PICKUP_CD_MULT[form]
    return entry


# ---------------------------------------------------------------------------
# W: Hyper (Mini every-3rd-hit on-hit) / Wallop (Mega cast)
# ---------------------------------------------------------------------------

# Wallop "stun[s] them for 1.25 seconds"; the kind rides this construction
# rather than MODULE_CC because slot W is Mega-only as a cast — Mini's
# Hyper is an on-hit shell with no damage part of its own.
_wallop = simple_damage(
    attr="Physical Damage",
    dmg_type="physical",
    source=("W", 1),
    event_order_certified="single_hit",
)


def _hyper(ctx: SlotCtx) -> dict[str, Any] | None:
    """W Mini: magic proc every 3rd hit — flat + %target max HP + AP."""
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    leveling = find_named_leveling(ability, "Bonus Magic Damage")
    if leveling is None:
        return None

    per_proc = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
    name = ability_name(ability)
    return ability_on_hit_entry(
        name,
        rank,
        "magic",
        {
            "name": name,
            "damage_per_hit": per_proc / _HYPER_STACKS,
            "damage_type": "magic",
            "stacks_required": _HYPER_STACKS,
        },
    )


def _w(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Hyper (Mini on-hit) or Wallop (Mega cast) by form."""
    return _wallop(ctx) if _form_index(ctx) else _hyper(ctx)


# ---------------------------------------------------------------------------
# E: Hop (Mini) / Crunch (Mega)
# ---------------------------------------------------------------------------


def _hop(ctx: SlotCtx) -> dict[str, Any] | None:
    """E Mini: damage (6% of own max HP) + the Bonus Attack Speed buff."""
    ability = ctx.ability("E", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["stat_buff"] = {
        "bonus_attack_speed": extract_value(ability, "Bonus Attack Speed", rank)
    }
    entry["event_order_certified"] = "single_hit"
    return entry


def _crunch(ctx: SlotCtx) -> dict[str, Any] | None:
    """E Mega: single hit; own-max-HP unit resolved by local override."""
    ability = ctx.ability("E", 1)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    leveling = find_named_leveling(ability, "Physical Damage")
    if leveling is None:
        return None

    def _own_max_hp(unit: str, value: float) -> float | None:
        if unit.strip() == _CRUNCH_OWN_HP_UNIT:
            return value / 100.0 * ctx.stat("health")
        return None

    total = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=_own_max_hp
    )
    return damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
        event_order_certified="single_hit",
    )


def _e(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Hop (Mini) or Crunch (Mega) by form."""
    return _crunch(ctx) if _form_index(ctx) else _hop(ctx)


# ---------------------------------------------------------------------------
# R: GNAR! (Mega only)
# ---------------------------------------------------------------------------

_r_cast = by_option(
    "r_wall",
    {
        True: simple_damage(
            attr="Increased Damage",
            dmg_type="physical",
            event_order_certified="single_hit",
        ),
        False: simple_damage(
            attr="Physical Damage",
            dmg_type="physical",
            event_order_certified="single_hit",
        ),
    },
    default=True,
)


def _r(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Mega-only cast; Mini Gnar cannot cast it (emits nothing)."""
    entry = _r_cast(ctx) if _form_index(ctx) else None
    if entry is None or not bool(ctx.option("r_wall")):
        return entry
    # The cast's own control is the knock away MODULE_CC declares on the
    # damage part.  The wall branch adds a second, separate control: enemies
    # that "collide with terrain ... are stunned instantly instead of slowed
    # after a delay", for the cached Disable Duration.  It is its own
    # interval rather than the part's kind, because one part carries one
    # kind and the knock away is what the damage lands with.
    duration = extract_value(ctx.ability(), "Disable Duration", ctx.rank_for())
    entry["control_events"] = (ControlEvent("stun", duration),)
    return entry


OPTIONS = [
    bool_option("mega", False, label="Mega Gnar form"),
    bool_option("q_pickup", True, label="Catch Q (boomerang/boulder)"),
    bool_option("r_wall", True, label="R into wall (1.5x damage + sourced stun)"),
    int_option(
        "q_secondary_targets",
        0,
        minimum=0,
        maximum=5,
        label="Mini Q: enemies hit on the boomerang's return pass (each "
        "takes the sourced 50% Reduced Damage row; Mega's boulder "
        "stops on the first enemy)",
        rotation={"role": "irrelevant", "slot": "Q"},
    ),
]

ASSUMPTIONS = [
    "Mega form stat bonuses are module constants from the live game "
    "files (the JSON passive parse is empty and the wiki's Mega stat "
    "box is stale); they are base-stat increases, so bonus AD is "
    "unchanged",
    "W Hyper procs every 3rd basic attack (on-hit model; in-game "
    "ability hits also add stacks, so this is slightly conservative)",
    "Hyper's 300 damage cap vs monsters ignored (champion targets)",
    "E Hop assumes the bounce lands on an enemy (damage + attack speed "
    "buff always included)",
    "Q Mini prices the primary hit at full damage plus one sourced 50% "
    "Reduced Damage hit per q_secondary_targets on the return pass "
    "(default 0); enemies can be hit only once per pass, and Mega's "
    "boulder stops on the first enemy (no reduced row)",
    "Mega E shockwave hits a single target once (no double-dip)",
    "R is unavailable in Mini form (emits no damage entry); the Mega wall "
    "branch carries the sourced stun interval, and the open branch the "
    "knock-away, whose duration the cache does not carry",
    "Forms share ability cooldowns",
]

SLOTS = {
    "P": _rage_gene,
    "Q": _q,
    "W": _w,
    "E": _e,
    "R": _r,
}

# Both Q forms slow "for 2 seconds" and both E forms slow "by 80% for 0.5
# seconds", so each slot has one answer across the form swap.  R is
# Mega-only and "knock[s] away nearby enemies" before its damage — the
# knockback is the immobilize the damage lands with under either r_wall
# branch, and the wall branch's terrain stun is a second control the slot
# authors on top of it (see ``_r``).  W's kind rides Wallop itself (above)
# because Mini's W is an on-hit shell; P is the Mega stat-buff row and
# applies nothing.
MODULE_CC = {"Q": "slow", "W": "stun", "E": "slow", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Gnar", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Gnar")
