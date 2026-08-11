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

from ..stats import growth_stat
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
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

# HARDCODED: verify on patch updates — against the GAME FILES, not the
# wiki: https://raw.communitydragon.org/latest/game/data/characters/
# gnarbig/gnarbig.bin.json (CharacterRecords/Root) minus gnar's. The
# wiki's Mega stat box is stale (claims 5.7 AD growth; the game says
# 5.5 — confirmed by in-game testing).
# Mega Gnar (the in-game GnarBig unit) stat deltas vs Mini as
# (base, growth) pairs through the standard growth formula — the Rage
# Gene passive's JSON leveling is empty, so the values live here (see
# CLAUDE.md "Known-degraded wiki parses"). These are BASE-stat deltas
# (GnarBig's own base stat block): the AD counts as base AD, never
# bonus AD — R's %bonus-AD ratios see 0 without items. Attack speed is
# a LOSS in percentage points of bonus attack speed (it cancels Mini's
# growth-derived bonus AS: 6%/level Mini vs 0.5%/level Mega).
MEGA_BONUS_HEALTH = (100.0, 43.0)  # 640/122 vs 540/79: +831 at level 18
MEGA_BONUS_AD = (6.0, 2.3)  # 66/5.5 vs 60/3.2: +45.1 at level 18
MEGA_BONUS_ARMOR = (4.0, 3.0)  # 36/6.7 vs 32/3.7: +55 at level 18
MEGA_BONUS_MR = (3.0, 3.5)  # 33/4.8 vs 30/1.3: +62.5 at level 18
MEGA_ATTACK_SPEED_LOSS = (0.0, 5.5)  # 0.5 vs 6.0/lvl: -93.5 at level 18

# HARDCODED: catching Q refunds 40% (Mini) / 70% (Mega) of the
# cooldown (wiki prose) -> remaining-cooldown multiplier per form.
_Q_PICKUP_CD_MULT = (0.6, 0.3)

# Hyper procs on every 3rd basic attack (wiki prose, not JSON).
_HYPER_STACKS = 3

# Crunch's own-max-HP unit, unknown to scaling.py's shared unit table.
_CRUNCH_OWN_HP_UNIT = "% of his maximum health"


def _form_index(ctx: SlotCtx) -> int:
    """JSON entry index for the current form: 0 = Mini, 1 = Mega."""
    return 1 if ctx.options.get("mega", False) else 0


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

    entry = damage_entry(ability.get("name", "Rage Gene"), 0, 0.0, 0.0, "physical")
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

_q_forms = (
    simple_damage(attr="Physical Damage", dmg_type="physical", source=("Q", 0)),
    simple_damage(attr="Physical Damage", dmg_type="physical", source=("Q", 1)),
)


def _q(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: form-picked "Physical Damage"; catching it refunds cooldown."""
    form = _form_index(ctx)
    entry = _q_forms[form](ctx)
    if entry is not None and ctx.options.get("q_pickup", True):
        entry["cooldown"] *= _Q_PICKUP_CD_MULT[form]
    return entry


# ---------------------------------------------------------------------------
# W: Hyper (Mini every-3rd-hit on-hit) / Wallop (Mega cast)
# ---------------------------------------------------------------------------

_wallop = simple_damage(attr="Physical Damage", dmg_type="physical", source=("W", 1))


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
    name = ability.get("name", "Hyper")
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
        ability.get("name", "Hop"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["stat_buff"] = {
        "bonus_attack_speed": extract_value(ability, "Bonus Attack Speed", rank)
    }
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
        ability.get("name", "Crunch"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
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
        True: simple_damage(attr="Increased Damage", dmg_type="physical"),
        False: simple_damage(attr="Physical Damage", dmg_type="physical"),
    },
    default=True,
)


def _r(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Mega-only cast; Mini Gnar cannot cast it (emits nothing)."""
    return _r_cast(ctx) if _form_index(ctx) else None


OPTIONS = [
    {
        "key": "mega",
        "type": "bool",
        "default": False,
        "label": "Mega Gnar form",
    },
    {
        "key": "q_pickup",
        "type": "bool",
        "default": True,
        "label": "Catch Q (boomerang/boulder)",
    },
    {
        "key": "r_wall",
        "type": "bool",
        "default": True,
        "label": "R into wall (1.5x damage + stun)",
    },
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
    "Q Boomerang 'Reduced Damage' (subsequent targets) not modeled — "
    "single-target full damage, one hit per throw",
    "Mega E shockwave hits a single target once (no double-dip)",
    "R is unavailable in Mini form (emits no damage entry)",
    "Forms share ability cooldowns",
]

SLOTS = {
    "P": _rage_gene,
    "Q": _q,
    "W": _w,
    "E": _e,
    "R": _r,
}

parse_abilities = build_parser(SLOTS, "Gnar")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Gnar",
        "revision_id": 4008132,
        "revision_timestamp": "2026-04-13T18:59:15Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
