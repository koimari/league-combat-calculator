"""Zaahen — CP10.10 full-entry-reviewed packet module.

Wiki-sourced item on-hit application is attached as a post-process on the
batch parser output (the batch parser builds its slot map at build time, so
declarations cannot be injected into the slot dict after the fact).

Row-selection fix (W): Dreaded Return "extends his glaive in the target
direction, dealing physical damage to enemies hit.  Upon reaching maximum
range, all enemies hit are dealt physical damage".  The generated packet
priced only the first leg — "Initial Physical Damage"
(40/60/80/100/120 + 50% bonus AD) — dropping the "Subsequent Physical
Damage" row (30/50/70/90/110 + 30% bonus AD).  This module prices the
cache's "Total Physical Damage" (70/110/150/190/230 + 80% bonus AD),
which is the two summed.  Two legs is not one hit, so W declares its
aggregate at the cast boundary instead of certifying a single hit; the
glaive's travel time to maximum range is not in the entry, so the second
leg's offset is left for the timing wave.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .module_helpers import typed_damage
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "5f5796aa0364becd253cbb3b7b05939147841a3f76e41cfa061242d344ec9f63"

# Grim Deliverance's damage is the slam's, not the launch's: "He then slams
# his glaive down after a 0.6-second delay, unleashing a shockwave that
# deals physical damage to nearby enemies" (cached R prose).
_R_SLAM_DELAY_SECONDS = 0.6


def _darkin_glaive(ctx: SlotCtx) -> dict[str, Any] | None:
    """Price the selected Q row from Zaahen's three sourced Q variants."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    try:
        variant = int(ctx.option("q_variant"))
    except (TypeError, ValueError):
        variant = 0
    variant = max(0, min(variant, 2))
    attributes = (
        "Total Physical Damage",
        "Physical Damage per Hit",
        "Bonus Physical Damage",
    )
    attribute = attributes[variant]
    sourced_amount = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    count = 2 if variant < 2 else 1
    amount = sourced_amount / 2.0 if variant == 0 else sourced_amount
    entry = damage_entry(
        ability.get("name", "The Darkin Glaive"),
        rank,
        extract_cooldown(ability, rank),
        sourced_amount if variant != 1 else sourced_amount * count,
        "physical",
    )
    # The knock-up is a property of the variant, not of the slot, so it is
    # authored here rather than in MODULE_CC: variants 0 and 1 price the
    # first cast, whose two strikes only "deal modified physical damage",
    # while variant 2's "Bonus Physical Damage" is the recast, which alone
    # "knock[s] up the target for 0.75 seconds".
    entry["parts"] = (
        DamagePart(
            "physical",
            amount=amount,
            count=count,
            time_offset=0.0,
            hit_interval=0.0,
            cc_kind="knockup" if variant == 2 else "none",
        ),
    )
    entry["detail"] = f"Q variant: {attribute}."
    return entry


_darkin_glaive.phase = "damage"


def _dreaded_return(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the extension plus the maximum-range hit, declared at the cast."""
    return typed_damage(ctx, "Total Physical Damage", "physical", time_offset=0.0)


# Dreaded Return's glaive reaches its end and "all enemies hit are dealt
# physical damage, stunned for 0.25 seconds, and pulled 225 units toward
# Zaahen" — the cast stuns the target it damages, and the row now prices
# both of the cast's legs.  Aureate Rush only flourishes, and Grim
# Deliverance's shockwave only slams.  Q is not here: its knock-up belongs
# to the recast variant, so the kind is authored per part in
# ``_darkin_glaive``.  P is the Determination stack buff and authors no
# damage part.
MODULE_CC = {"W": "stun", "E": "none", "R": "none"}

_base_parse, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zaahen",
    PACKET_SHA256,
    assumption_overrides=(
        "The Darkin Glaive prices both strikes (Physical Damage per Hit x 2 "
        "== Total Physical Damage).",
        "Dreaded Return prices both legs — the cached Total Physical "
        "Damage row (70/110/150/190/230 + 80% bonus AD) == Initial "
        "Physical Damage + Subsequent Physical Damage.  The generated "
        "packet priced the Initial leg alone.  The aggregate is declared "
        "at the cast boundary; the glaive's travel to maximum range is "
        "not authored.",
    ),
    # E's flourish is one hit at the cast; its packet carries no travel or
    # tick phase to place.  W prices two legs and declares their aggregate
    # at the cast instead.
    single_hit_slots=frozenset({"E"}),
    # "He then slams his glaive down after a 0.6-second delay, unleashing a
    # shockwave that deals physical damage" — R's hit is the slam's.
    packet_part_timings={"R": {"time_offset": _R_SLAM_DELAY_SECONDS}},
    slot_parsers={
        "Q": _darkin_glaive,
        "W": _dreaded_return,
    },
    cc_kinds=MODULE_CC,
)
PACKET_SPEC = SLOTS.packet_spec

OPTIONS = list(OPTIONS) + [
    {
        "key": "q_variant",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "Q damage variant",
    }
]

_ON_HIT_SPECS: dict[str, dict] = {
    "Q": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

_parse_abilities = _base_parse


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


# The contract surveys the declaration against what the parser carries, and
# the module's public parser is this wrapper — so it carries the same dict
# the compiled parser was built with.
parse_abilities.cc_kinds = _base_parse.cc_kinds


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Zaahen")
