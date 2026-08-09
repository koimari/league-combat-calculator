"""Naafiri — CP10.5 full-entry-reviewed packet module (E2/E9-2 fixes).

E2 DoT fix: Q (Darkin Daggers) prices the initial hit plus 10 sourced
0.5s bleed ticks (Total Bleed Physical Damage == per-tick x 10).

E9-2 gap fixes:
- Q recast: the recast hits an already-bleeding champion for the
  "remaining bleed damage plus additional bonus physical damage".  The
  bonus is the cached Minimum/Maximum Bonus Physical Damage rows (30-80
  + 40% bAD at the minimum, 60-160 + 140% bAD at the maximum),
  interpolated 0% : 100% by the target's missing health; the remaining
  bleed term is covered by the already-priced bleed ticks (conservative:
  the recast does not double-price them).
- Q self-heal: the recast against a champion heals Naafiri for the
  cached "Heal" row (45-105 + 40% bonus AD) — authored by the E1
  self-heal rule (HEALING_RULE_CHAMPIONS); the support scanner defers
  this slot so the ledger has one receipt.
- E (Eviscerate) prices BOTH the dash and the Flurry explosion on
  arrival (Dash Physical Damage + Flurry Physical Damage == Total
  Physical Damage), instead of the packet's dash-only row.
- P packmate summon and the W/R shields stay documented out.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "422062ecdd781eb5a57f34b7b9c3221288b03f12811cb2d0788a6a877afe4896"

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_packet_module(
        "Naafiri",
        PACKET_SHA256,
        packet_tick_fixes={
            "Darkin Daggers": {
                "initial_tick": 0.0,
                "extra_part": {
                    "attribute": "Bleed Physical Damage per Tick",
                    "count": 10,
                    "damage_type": "physical",
                    "first_tick": 0.5,
                    "tick_interval": 0.5,
                    "dot_duration": 5.0,
                },
            }
        },
    )
)
PACKET_SPEC = _packet_slots.packet_spec

# HARDCODED: verify on patch updates — the sourced bleed tick count:
# Total Bleed Physical Damage == Bleed Physical Damage per Tick x 10 at
# every rank (E2 worklist, data/worklists/e2-dot-ticks.json), with the
# wiki's 0.5s cadence over 5 seconds.  The recast fires 0.5s after the
# first cast ("can be recast after 0.5 seconds and within 4 seconds").
_BLEED_TICKS = 10
_BLEED_FIRST_TICK = 0.5
_BLEED_TICK_INTERVAL = 0.5
_BLEED_DURATION = 5.0
_RECAST_TIME_OFFSET = 0.5


def _darkin_daggers(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: initial dagger + 10 bleed ticks + the recast's bonus damage."""
    ability = ctx.ability("Q", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None

    initial = extract_named(
        ability, "Initial Physical Damage", rank, ctx.stats, ctx.target
    )
    per_tick = extract_named(
        ability, "Bleed Physical Damage per Tick", rank, ctx.stats, ctx.target
    )
    parts: list[DamagePart] = [
        DamagePart("physical", initial, time_offset=0.0),
        DamagePart(
            "physical",
            per_tick,
            count=_BLEED_TICKS,
            time_offset=_BLEED_FIRST_TICK,
            hit_interval=_BLEED_TICK_INTERVAL,
        ),
    ]
    total = initial + per_tick * _BLEED_TICKS

    if bool(ctx.options.get("q_recast", True)):
        minimum = extract_named(
            ability, "Minimum Bonus Physical Damage", rank, ctx.stats, ctx.target
        )
        maximum = extract_named(
            ability, "Maximum Bonus Physical Damage", rank, ctx.stats, ctx.target
        )

        def recast_bonus(missing_ratio: float) -> float:
            return minimum + (maximum - minimum) * missing_ratio

        parts.append(
            DamagePart(
                "physical",
                hp_scaled_damage=recast_bonus,
                time_offset=_RECAST_TIME_OFFSET,
            )
        )
        total += minimum

    entry = damage_entry(
        ability.get("name", "Darkin Daggers"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = tuple(parts)
    entry["dot_duration"] = _BLEED_DURATION
    entry["detail"] = (
        f"Initial hit + {_BLEED_TICKS} sourced 0.5s-interval bleed ticks "
        f"(Bleed Physical Damage per Tick x{_BLEED_TICKS} = Total Bleed "
        "Physical Damage)"
        + (
            "; recast bonus damage interpolated between the Minimum/Maximum "
            "Bonus Physical Damage rows by target missing health"
            if bool(ctx.options.get("q_recast", True))
            else "; recast bonus not priced (q_recast off)"
        )
    )
    return entry


def _eviscerate(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: dash damage plus the Flurry explosion on arrival."""
    ability = ctx.ability("E", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None

    dash = extract_named(ability, "Dash Physical Damage", rank, ctx.stats, ctx.target)
    flurry = extract_named(
        ability, "Flurry Physical Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Eviscerate"),
        rank,
        extract_cooldown(ability, rank),
        dash + flurry,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", dash, time_offset=0.0),
        DamagePart("physical", flurry, time_offset=0.5),
    )
    entry["detail"] = (
        "Dash Physical Damage + Flurry Physical Damage == Total Physical "
        "Damage (the flurry explodes on arrival, 0.5s cadence authored)."
    )
    return entry


SLOTS = dict(_packet_slots)
SLOTS["Q"] = _darkin_daggers
SLOTS["E"] = _eviscerate
parse_abilities = build_parser(SLOTS, "Naafiri")

OPTIONS: list[dict[str, Any]] = list(_packet_options) + [
    {
        "key": "q_recast",
        "type": "bool",
        "default": True,
        "label": "Q recast hits the bleeding target (bonus damage + heal)",
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
    "Q (Darkin Daggers) prices the initial hit, 10 sourced 0.5s bleed "
    "ticks (Total Bleed Physical Damage == per-tick x 10, E2 worklist), "
    "and the recast's bonus damage — interpolated between the "
    "Minimum/Maximum Bonus Physical Damage rows (0% : 100% based on "
    "target missing health) when q_recast is on (default); the remaining "
    "bleed damage of the recast is covered by the already-priced bleed "
    "ticks and is not double-counted",
    "Q recast against a champion heals Naafiri for the cached Heal row "
    "(45-105 + 40% bonus AD) — one heal per Q cast, authored by the E1 "
    "self-heal rule; the support scanner defers this slot to keep one "
    "ledger receipt",
    "E (Eviscerate) prices the dash plus the Flurry explosion (Dash "
    "Physical Damage + Flurry Physical Damage == Total Physical Damage)",
    "P packmate summon and the W hunt / R shield stay documented "
    "out-of-scope state.",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Naafiri")
