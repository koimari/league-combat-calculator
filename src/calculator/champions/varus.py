"""Varus: slot map for the archetype engine.

W (Blighted Quiver) is an ON-HIT passive, not a castable: every basic attack
deals the "Bonus Magic Damage" row and applies a Blight stack, capped at three
over 6 refreshing seconds.
Q (Piercing Arrow) is the Blight DETONATOR: an ability consumes every stack for
"Bonus Magic Damage per Stack" apiece.  The engine has no auto-application to
ability-detonation cycle, so the detonation rides Q as a ``post_hit_proc``
priced from ``blight_stacks``, default 3, one per Q cast; E and R detonate in
game too, and re-stacking between casts is deliberately not double-priced.  Q
interpolates between the sourced Minimum and Maximum rows by ``q_charge_fraction``.
E (Hail of Arrows) is physical damage, which both the game and the cache say.
P (Living Vengeance) is an on-takedown steroid: +30% bonus attack speed and, off
the resulting TOTAL bonus attack speed, 33% of it again as both attack damage and
ability power.  All three are cached prose, and it is gated on
``p_champion_takedown``, because a damage package does not imply a takedown.
R (Chain of Corruption) reads "Magic Damage" and attaches the sourced 2-second
root to the primary hit; the chain spread is outside a single-target model.
"""

import re
from typing import Any

from ..ability_prose import CachedSentence
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx, build_parser
from .inputs import bool_option, float_option, int_option
from .module_helpers import ability_slot, missing_hp_fraction, ranked_slot
from .shared_option_keys import TARGET_MISSING_HP_OPTION
from .slot_control import with_control
from .slot_entries import STEROID_ZERO, ability_on_hit_entry, damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# Blight's stack cap is the binary VarusW.MaxStacks DataValue; the cached
# prose corroborates ("stacks up to 3 times"); abilities detonate all stacks.
_BLIGHT_MAX_STACKS = int(data_value(spell_object("Varus", "VarusW"), "MaxStacks"))
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
    per_stack = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
    return per_stack * stacks


def _blight_per_stack(ctx: SlotCtx, rank: int) -> float:
    """One Blight stack's own damage, for the level the fight counts."""
    ability = ctx.ability("W", 0)
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, _BLIGHT_DETONATION_ATTR)
    if leveling is None:
        return 0.0
    return sum_modifiers(leveling, rank, ctx.stats, ctx.target)


def _blight_stack_window(ctx: SlotCtx) -> dict[str, Any] | None:
    """The cached window a Blight stack holds, and what applies one.

    "Varus' basic attacks are empowered to ... apply a stack of Blight
    on-hit for 6 seconds, refreshing ... and stacking up to 3 times", so
    the swings stack it and the cache states both numbers.
    """
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    seconds, stacks = _BLIGHT_WINDOW.stack_terms(ability)
    return {
        "arming_slots": (),
        "max_stacks": stacks,
        "hits_required": stacks,
        "stacks_from_swings": True,
        "stack_seconds": seconds,
        "armed_at_start": False,
        "requested": False,
    }


_BLIGHT_WINDOW = CachedSentence(
    re.compile(
        r"apply a stack of Blight on-hit for (?P<seconds>\d+(?:\.\d+)?) seconds"
        r"[^.]*?stacking up to (?P<stacks>\d+) times"
    ),
    missing=(
        "Varus W: the cached entry no longer states Blight's stack life and "
        "cap ('for N seconds ... stacking up to N times')"
    ),
)


def _charge_fraction(ctx: SlotCtx) -> float:
    """Q charge fraction: 0.0 = minimum (0% charge) .. 1.0 = fully charged."""
    fraction = float(ctx.option("q_charge_fraction"))
    return min(max(fraction, 0.0), 1.0)


@ranked_slot
def _piercing_arrow(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: charge-interpolated arrow damage + the Blight detonation."""

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
            requested = ctx.options.get("blight_stacks")
            window = _blight_stack_window(ctx) if requested is None else None
            if window is not None:
                per_stack = _blight_per_stack(ctx, rank)
                parts.append(
                    DamagePart(
                        "magic",
                        detonation,
                        time_offset=0.0,
                        stack_scaled_damage=lambda level: per_stack * level,
                    )
                )
                entry["stack_window"] = window
                detail.append(
                    "Blight stacks consumed: the swings that applied them "
                    f"inside their {window['stack_seconds']:g}s window, at "
                    f"{rank} points in W"
                )
            else:
                parts.append(DamagePart("magic", detonation, time_offset=0.0))
                detail.append(
                    f"{stacks} Blight stack(s) consumed at {rank} points in W"
                )
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


@ranked_slot
def _blighted_quiver(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: flat on-hit magic per basic attack (Blight stacks ride it)."""

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


# Living Vengeance's champion-takedown numbers are binary DataValues
# (VarusPassive.PassiveAS / AStoADChampion / AStoAPChampion); the cached P
# prose corroborates ("30% bonus attack speed ... equal to 33% of his total
# bonus attack speed").  The unit-kill branch's "10% / 15% / 20% (based on
# level)" names no breakpoint levels, so pricing it would mean inventing
# them.
_VARUS_P_SPELL = spell_object("Varus", "VarusPassive")
_P_TAKEDOWN_ATTACK_SPEED = data_value(_VARUS_P_SPELL, "PassiveAS") * 100.0
_P_TAKEDOWN_DERIVED_RATIO = data_value(_VARUS_P_SPELL, "AStoADChampion") / 100.0


@ability_slot()
def _living_vengeance(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: the takedown-empowered attack speed, and the AD/AP it derives."""

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
        label=(
            "Blight stacks at detonation; unset derives them from the swings "
            "that applied Blight inside its cached window"
        ),
        derives=True,
        rotation={
            "role": "consume",
            "slot": "Q",
            "condition": "blight",
            "kind": "stack_consume",
        },
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
        rotation={"role": "self_state", "slot": "Q"},
    ),
    bool_option(
        "w_active_empower",
        True,
        label="W active empowers the next Piercing Arrow (+% of the "
        "target's missing health as magic damage)",
        rotation={"role": "self_state", "slot": "W"},
    ),
    int_option(
        TARGET_MISSING_HP_OPTION,
        50,
        minimum=0,
        maximum=100,
        label="Target missing health %",
        rotation={
            "role": "execute",
            "slot": "Q",
            "condition": "execute",
            "kind": "execute",
        },
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
    "W (Blighted Quiver) is an on-hit passive: every basic attack deals 4 to 40 + 15% "
    "bonus AD + 25% AP.",
    "That is by rank, and each attack applies one Blight stack; stacks cap at 3 and "
    "refresh for 6s.",
    "Blight detonation is priced on Piercing Arrow once per Q cast, from the "
    "blight_stacks option.",
    "E and R also detonate in game, but re-stacking between casts is not "
    "double-priced, conservative.",
    "Detonation per stack is the sourced Bonus Magic Damage per Stack row.",
    "That is % of target maximum health + 1.3% per 100 AP by rank.",
    "Q's 0 to 50% charge bonus is not modeled: the arrow is priced at its Maximum "
    "row.",
    "W's active empowers the next Piercing Arrow for the sourced Active Maximum Magic "
    "Damage row.",
    "That is 9 to 21% of the target's missing health by W rank "
    "(data/champions.json W), priced at Maximum.",
    "It reads target_missing_hp_pct (default 50%); w_active_empower off prices an "
    "unempowered arrow.",
    "Q detonation requires the Q cast; with blight_stacks=0 the option "
    "models a fresh target and no detonation fires",
    "P (Living Vengeance) prices its champion-takedown branch when "
    "p_champion_takedown is on.",
    "P defaults off, because a takedown is not implied by a damage package.",
    "The branch is +30% bonus attack speed, with AD and AP each 33% of the resulting "
    "total bonus AS.",
    "That is cached P prose, since the passive carries no leveling row.",
    "Its unit-kill branch, 10/15/20% by level, is not priced: the cache names no "
    "level breakpoints.",
    "E is physical damage (JSON and in-game); the reviewed packet's "
    "magic label was a parser error, corrected here",
    "E's desecrated ground applies Grievous Wounds for 3 seconds (wiki prose).",
    "The coupled timeline wounds enemies it damages with the patch-wide 40% window.",
    "R's primary-target root is a sourced 2-second action lock.",
    "The secondary chain spread and Q's self-slow are outside the single-target "
    "model.",
    "P (Living Vengeance) deals no enemy damage; the reviewed packet declares it kind "
    "no_damage.",
    "The slot's priced row is the self steroid it grants, a zero-damage stat buff, "
    "not a hit.",
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
MODULE_CC = {"Q": "none", "E": "slow", "R": "root", "P": "none", "W": "none"}

parse_abilities = build_parser(SLOTS, "Varus", cc_kinds=MODULE_CC)

# No MODULE_COVERAGE: every one of the five slots emits a priced row now.

SOURCES = load_champion_sources("Varus")
