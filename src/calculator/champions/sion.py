"""Sion: slot map for the archetype engine.

Q (Decimating Smash) is a charged strike: the cache carries a "Minimum Physical
Damage" row and a "Maximum Physical Damage" row, the charge raising damage every
0.25 seconds to a cap of 2, and the slot interpolates between them by
``q_charge_fraction``, default 1.0 for a fully charged strike.  The neighbouring
"Maximum Base Damage Increase" row is a percentage, not a damage number.
W (Soul Furnace) is a plain "Magic Damage" read for the shield recast, target
maximum health included.
E (Roar of the Slayer) is a plain "Magic Damage" read.
R (Unstoppable Onslaught) prices the charge's maximum physical damage, the
max-charge boundary.
P (Glory in Death) deals no enemy damage and is an explicit no-damage slot.
"""

from typing import Any

from ..ability_spec import DamagePart
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .inputs import float_option
from .module_helpers import no_damage_parser, ranked_slot
from .slot_cc import CC_PER_PART
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources


@ranked_slot
def _decimating_smash(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: minimum/maximum physical damage interpolated by charge time."""
    fraction = max(0.0, min(1.0, float(ctx.option("q_charge_fraction"))))
    low = extract_named(ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target)
    high = extract_named(
        ability, "Maximum Physical Damage", rank, ctx.stats, ctx.target
    )
    value = low + (high - low) * fraction
    # Q's crowd control is charge-dependent, so it is authored on the part
    # rather than declared once in MODULE_CC: the uncharged recast is
    # "dealing physical damage to enemies hit and slowing them by 50%",
    # while "if Decimating Smash was charged for at least 1 second" — half
    # of the cached 2-second charge — Sion "instead slams his axe down ...
    # knocking them up ... and stunning them", two immobilize kinds at
    # once, which is what the un-narrowed reviewed kind names.
    charged = fraction >= 0.5
    return damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
        # One strike, one blow per target, at either charge.
        event_order_certified="single_hit",
        parts=(
            DamagePart("physical", value, cc_kind="immobilize" if charged else "slow"),
        ),
        detail=(
            f"Minimum/Maximum Physical Damage rows interpolated by charge "
            f"fraction {fraction:.2f}"
        ),
    )


@ranked_slot
def _roar_of_the_slayer(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: magic damage + the sourced 25% armor reduction for 4 seconds.

    The cached E description pins the debuff ("inflicts them with 25%
    armor reduction for 4 seconds"); damage.py applies a target_debuff
    AFTER this ability's own damage, so every later physical hit (autos,
    Q, R) benefits but the E hit itself does not.
    """
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value),),
        # One shockwave, "magic damage to the first enemy hit".
        "event_order_certified": "single_hit",
        "target_debuff": {
            "armor_reduction_percent": 25.0,
            "duration": 4.0,
        },
        "detail": (
            "Magic Damage row plus the cached 25% armor reduction for 4 "
            "seconds (wiki prose on E); the shred applies after E's own "
            "hit."
        ),
    }


ASSUMPTIONS = [
    "Q (Decimating Smash) interpolates the Minimum and Maximum Physical Damage rows "
    "by charge time.",
    "Q's default is fully charged, q_charge_fraction 1.0.",
    "R (Unstoppable Onslaught) prices the maximum-charge slam (Maximum "
    "Physical Damage row).",
    "P deals no enemy damage and is an explicit no-damage slot.",
    "E (Roar of the Slayer) inflicts the cached 25% armor reduction for 4 seconds "
    "(wiki prose on E).",
    "The target_debuff applies after E's own damage, so later autos, Q and R benefit.",
]

SOURCES = load_champion_sources("Sion")

SLOTS = {
    "P": no_damage_parser(
        "P",
        "Glory in Death is a post-death reanimation state; no enemy damage.",
    ),
    "Q": _decimating_smash,
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "E": _roar_of_the_slayer,
    "R": simple_damage(
        attr="Maximum Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
}

# Reviewed crowd control, read from the cached kit.  W (Soul Furnace)
# "consumes the shield to deal magic damage to nearby enemies" and applies
# nothing.  E (Roar of the Slayer) "slows them for 2.5 seconds"; its stun
# and knock-back are gated on the target being "a minion or non-epic
# monster".  R (Unstoppable Onslaught): every enemy "hit by the slam are
# dealt the same damage and are slowed for 3 seconds", while the pull and
# stun reach only "enemies in a smaller radius", which the duel model does
# not place.  Q's answer is charge-dependent and is authored on its part.
MODULE_CC = {"Q": CC_PER_PART, "W": "none", "E": "slow", "R": "slow", "P": "none"}

MODULE_COVERAGE = coverage(no_damage="P")

OPTIONS = [
    float_option(
        "q_charge_fraction",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Q charge fraction",
        step=0.25,
        rotation={"role": "self_state", "slot": "Q"},
    ),
]

parse_abilities = build_parser(SLOTS, "Sion", cc_kinds=MODULE_CC)
