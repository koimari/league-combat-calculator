"""Varus — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- W (Blighted Quiver) is an ON-HIT passive, not a castable: every basic
  attack deals the "Bonus Magic Damage" leveling row and applies a Blight
  stack (max 3, 6s, refreshing). The reviewed packet priced this row as a
  40s-cooldown cast, which contributed ~0 damage in any real fight; the
  on-hit shell (Vayne W precedent) prices it per auto instead.
- Q (Piercing Arrow) is the primary Blight DETONATOR: abilities consume
  all Blight stacks on the target, dealing "Bonus Magic Damage per Stack"
  (% of the target's max health + % per 100 AP) per stack. The fight
  engine has no auto-application->ability-detonation cycle, so the
  detonation rides Q as a ``post_hit_proc`` priced from the
  ``blight_stacks`` option (default 3 = the sourced max) — one sourced
  detonation per Q cast. E and R also detonate in-game; re-stacking a
  target between casts is not double-priced here (conservative single
  detonator model). Q interpolates between the sourced Minimum/Maximum damage rows by
  the q_charge_fraction option (default 1.0 = fully charged; the
  0-50% charge ramp is the wiki prose).
- E (Hail of Arrows) is physical damage ("Physical Damage" — the packet's
  magic label was wrong; in-game and the JSON both say physical).
- P (Living Vengeance) is an on-takedown steroid: +30% bonus attack
  speed and, derived from the resulting TOTAL bonus attack speed, 33% of
  it again as both attack damage and ability power.  All three numbers
  are cached prose (the passive has no leveling row), and the whole
  thing is gated on ``p_champion_takedown`` because a takedown is not
  implied by a damage package.
- R (Chain of Corruption) reads "Magic Damage" and attaches the sourced
  2-second root to the primary hit; secondary chain spread stays outside the
  single-target model.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import missing_hp_fraction
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
    with_control,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option, float_option, int_option

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Blight stacks to 3 on basic attacks; abilities detonate all stacks.
_BLIGHT_MAX_STACKS = 3
_BLIGHT_DETONATION_ATTR = "Bonus Magic Damage per Stack"


def _w_active_empower(ctx: SlotCtx, rank: int) -> float:
    """W active: the next Q is empowered with % of the target's MISSING
    health as bonus magic damage.

    Cached W prose: "Varus' next Piercing Arrow within 5.5 seconds is
    empowered to deal additional bonus magic damage, increased by 0% :
    50% (based on Piercing Arrow's charge time)".  Q is priced at its
    Maximum (fully-charged) rows, so the empower is priced at the
    sourced "Active Maximum Magic Damage" row (9-21% of missing health
    by W rank) against the shared ``target_missing_hp_pct`` option.
    """
    if not ctx.option("w_active_empower"):
        return 0.0
    ability = ctx.ability("W", 0)
    if ability is None:
        return 0.0
    # Raw percent read: the "% of target's missing health" unit resolves
    # to 0 through the generic scaling core (the fight's target context
    # starts at full health), so the percent is read flat and priced
    # against the shared target_missing_hp_pct option.
    percent = extract_value(ability, "Active Maximum Magic Damage", rank)
    missing_health = float(ctx.target_stat("target_max_health") or 0.0) * (
        missing_hp_fraction(ctx)
    )
    return percent / 100.0 * missing_health


def _blight_detonation(ctx: SlotCtx, rank: int) -> float:
    """One full detonation: ``blight_stacks`` x per-stack %maxHP damage.

    The per-stack row is "% of the target's maximum health" plus
    "% per 100 AP" — both units resolve through the shared scaling core.
    """
    ability = ctx.ability("W", 0)
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, _BLIGHT_DETONATION_ATTR)
    if leveling is None:
        raise ValueError(
            "Varus W: 'Bonus Magic Damage per Stack' is missing from the "
            "ability JSON — cannot compute the Blight detonation"
        )
    stacks = min(
        _BLIGHT_MAX_STACKS,
        max(0, int(ctx.options.get("blight_stacks", _BLIGHT_MAX_STACKS))),
    )
    if stacks <= 0:
        return 0.0
    per_stack = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
    return per_stack * stacks


def _charge_fraction(ctx: SlotCtx) -> float:
    """Q charge fraction: 0.0 = minimum (0% charge) .. 1.0 = fully charged."""
    fraction = float(ctx.option("q_charge_fraction"))
    return min(max(fraction, 0.0), 1.0)


def _piercing_arrow(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: charge-interpolated arrow damage + the Blight detonation."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    fraction = _charge_fraction(ctx)
    minimum = extract_named(
        ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target
    )
    maximum = extract_named(
        ability, "Maximum Physical Damage", rank, ctx.stats, ctx.target
    )
    # The sourced rows are exact endpoints of the 0% : 50% charge ramp
    # (80/53.33 = 120/80 = 1.5 at every rank, including the % bonus AD
    # modifiers), so interpolation is the sourced 0-50% scaling.
    arrow = minimum + (maximum - minimum) * fraction
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        arrow,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", arrow),)
    entry["event_order_certified"] = "single_hit"
    if fraction < 1.0:
        entry["detail"] = (
            f"{fraction * 100:g}% charge: {arrow:g} physical "
            f"(between the sourced Minimum {minimum:g} and Maximum "
            f"{maximum:g} rows)"
        )

    detonation = _blight_detonation(ctx, rank)
    empower = _w_active_empower(ctx, rank)
    if detonation > 0 or empower > 0:
        stacks = min(
            _BLIGHT_MAX_STACKS,
            max(0, int(ctx.option("blight_stacks"))),
        )
        parts = []
        detail = []
        if detonation > 0:
            parts.append(DamagePart("magic", detonation, time_offset=0.0))
            detail.append(f"{stacks} Blight stack(s) consumed at {rank} points in W")
        if empower > 0:
            parts.append(DamagePart("magic", empower, time_offset=0.0))
            empower_detail = (
                f"W-active empower: {empower:g} magic "
                f"({missing_hp_fraction(ctx) * 100:g}% missing health "
                f"x Active Maximum Magic Damage {rank} points in W)"
            )
            detail.append(empower_detail)
        entry["post_hit_proc"] = {
            "name": "Blight Detonation",
            "breakdown_key": "blight_detonation",
            "parts": tuple(parts),
            "detail": "; ".join(detail),
        }
        entry["total_raw"] = arrow + detonation + empower
    return entry


def _blighted_quiver(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: flat on-hit magic per basic attack (Blight stacks ride it)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    leveling = find_named_leveling(ability, "Bonus Magic Damage")
    if leveling is None:
        raise ValueError(
            "Varus W: 'Bonus Magic Damage' leveling entry missing from the "
            "ability JSON — cannot compute the on-hit damage"
        )
    per_hit = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
    name = ability_name(ability)
    entry = ability_on_hit_entry(
        name,
        rank,
        "magic",
        {
            "name": name,
            "damage_per_hit": per_hit,
            "damage_type": "magic",
        },
    )
    entry["event_order_certified"] = "auto_stack_proc"
    return entry


# HARDCODED: verify on patch updates — Living Vengeance carries no
# leveling row at all; every number is cached P prose.  Only the
# champion-takedown branch is priced, because it is the one whose
# magnitudes the cache states without level breakpoints: "30% bonus
# attack speed as well as bonus attack damage and ability power equal to
# 33% of his total bonus attack speed".  The unit-kill branch's
# "10% / 15% / 20% (based on level)" names no breakpoint levels, so
# pricing it would mean inventing them.
_P_TAKEDOWN_ATTACK_SPEED = 30.0
_P_TAKEDOWN_DERIVED_RATIO = 0.33


def _living_vengeance(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the takedown-empowered attack speed, and the AD/AP it derives."""
    ability = ctx.ability()
    if ability is None:
        return None

    armed = bool(ctx.option("p_champion_takedown"))
    bonus_as = _P_TAKEDOWN_ATTACK_SPEED if armed else 0.0
    total_bonus_as = ctx.stat("bonus_attack_speed") + bonus_as
    derived = _P_TAKEDOWN_DERIVED_RATIO * total_bonus_as if armed else 0.0
    if armed:
        ctx.stats["bonus_attack_speed"] = total_bonus_as
        ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + derived
        ctx.stats["attack_damage"] = ctx.stat("attack_damage") + derived
        ctx.stats["ability_power"] = ctx.stat("ability_power") + derived
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {
        "bonus_attack_speed": bonus_as,
        "bonus_attack_damage": derived,
        "ability_power": derived,
    }
    entry["detail"] = (
        f"champion takedown: +{bonus_as:g}% bonus attack speed, and "
        f"+{derived:.2f} attack damage and ability power "
        f"({_P_TAKEDOWN_DERIVED_RATIO * 100:g}% of the resulting "
        f"{total_bonus_as:g}% total bonus attack speed)"
        if armed
        else (
            "not armed: Living Vengeance needs a kill or takedown, which "
            "a damage package does not imply.  The unit-kill branch "
            "(10%/15%/20% by level) is unpriced either way — the cache "
            "states no level breakpoints for it"
        )
    )
    return entry


_living_vengeance.phase = BUFF


# HARDCODED: verify on patch updates — wiki prose in the cached E JSON
# ("...inflicting them with Grievous Wounds").  Hail of Arrows' desecrated
# area applies the patch-wide 40% Grievous Wounds window; the strength and
# 3-second duration are the engine constants, not module numbers.
GRIEVOUS_WOUNDS_SOURCES = frozenset({"E"})

OPTIONS: list[dict[str, Any]] = [
    int_option(
        "blight_stacks",
        _BLIGHT_MAX_STACKS,
        minimum=0,
        maximum=_BLIGHT_MAX_STACKS,
        label="Blight stacks on the target when Piercing Arrow lands "
        "(3 = fully stacked; the Q detonation consumes them)",
    ),
    float_option(
        "q_charge_fraction",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Piercing Arrow channel charge (1.0 = fully charged; the "
        "arrow interpolates between the sourced Minimum and Maximum "
        "damage rows)",
        step=0.25,
    ),
    bool_option(
        "w_active_empower",
        True,
        label="W active empowers the next Piercing Arrow (+% of the "
        "target's missing health as magic damage)",
    ),
    int_option(
        "target_missing_hp_pct",
        50,
        minimum=0,
        maximum=100,
        label="Target missing health %",
    ),
    bool_option(
        "p_champion_takedown",
        False,
        label="Living Vengeance is empowered by a champion takedown",
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": (
                "A takedown outside the modeled rotation arms P's own "
                "buff — self-state, with no cross-slot cast edge."
            ),
        },
    ),
]

ASSUMPTIONS = [
    "W (Blighted Quiver) is an on-hit passive: every basic attack deals "
    "its bonus magic damage (4-40 + 15% bonus AD + 25% AP by rank) and "
    "applies one Blight stack; stacks cap at 3 and refresh for 6s",
    "Blight detonation is priced on Piercing Arrow (the primary "
    "detonator) once per Q cast from the blight_stacks option — E and R "
    "also detonate in-game, but re-stacking between casts is not "
    "double-priced in this single-target rotation (conservative)",
    "Detonation per stack = the sourced 'Bonus Magic Damage per Stack' "
    "row (% of target max health + 1.3% per 100 AP by rank); Q's "
    "0-50% charge bonus (the 'Maximum' rows) is not modeled — the "
    "arrow itself is priced at its Maximum (fully-charged) row",
    "W active empower: the next Piercing Arrow is empowered for the "
    "sourced 'Active Maximum Magic Damage' row (9-21% of the target's "
    "missing health by W rank, data/champions.json W) — priced at "
    "Maximum like the arrow, against the target_missing_hp_pct option "
    "(default 50%); toggle w_active_empower off to price an unempowered "
    "arrow",
    "Q detonation requires the Q cast; with blight_stacks=0 the option "
    "models a fresh target and no detonation fires",
    "P (Living Vengeance) prices its champion-takedown branch when "
    "p_champion_takedown is on (default off, because a takedown is not "
    "implied by a damage package): +30% bonus attack speed, and attack "
    "damage and ability power each equal to 33% of the resulting total "
    "bonus attack speed — cached P prose, since the passive carries no "
    "leveling row.  Its unit-kill branch (10%/15%/20% by level) is not "
    "priced: the cache names no level breakpoints for it",
    "E is physical damage (JSON and in-game); the reviewed packet's "
    "magic label was a parser error, corrected here",
    "E's desecrated ground applies Grievous Wounds for 3 seconds (wiki "
    "prose); the coupled timeline wounds enemies it damages with the "
    "patch-wide 40% window",
    "R's primary-target root is a sourced 2-second action lock; secondary "
    "chain spread and Q's self-slow are outside the single-target model",
    "P (Living Vengeance) deals no enemy damage — the pinned reviewed "
    "packet declares it kind='no_damage' — so the slot's priced row is "
    "the self steroid it grants (a zero-damage stat buff), not a hit.",
]


SLOTS = {
    "Q": _piercing_arrow,
    "W": _blighted_quiver,
    "E": simple_damage(
        attr="Physical Damage", dmg_type="physical", event_order_certified="single_hit"
    ),
    # The root is sourced off the cached "Root Duration" row rather than
    # only declared, so the part carries its own duration and atom.
    "R": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Root Duration",
    ),
    "P": _living_vengeance,
}

# Reviewed crowd control, read from the cached kit.  Q (Piercing Arrow)
# "deals physical damage to enemies hit" — the 20% slow in its text is on
# Varus himself while he charges, not on the target.  E (Hail of Arrows)
# lands, then "the area then becomes desecrated for 4 seconds, slowing
# enemies within".  R (Chain of Corruption) infects the first champion
# hit, "dealing magic damage and rooting them for 2 seconds".  W is an
# on-hit Blight rider with no cast damage and P is a kill-triggered stat
# buff.
MODULE_CC = {"Q": "none", "E": "slow", "R": "root"}

parse_abilities = build_parser(SLOTS, "Varus", cc_kinds=MODULE_CC)

# No MODULE_COVERAGE: every one of the five slots emits a priced row now.

SOURCES = load_champion_sources("Varus")
