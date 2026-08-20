"""Vladimir — CP10.9 full-entry-reviewed packet module.

P1-3 closure — R (Hemoplague) damage amplification: the reviewed R
packet priced only the detonation burst (plus the E1 heal family).  The
plague also "infects enemies hit for 4 seconds, increasing the damage
they take from all sources by 10%" (data/champions.json R prose; the
wiki's Hemoplague notes state it "amplifies itself for an actual damage
of 165 / 275 / 385 (+ 77% AP)" — the 150/250/350 (+ 70% AP) detonation
plus its own 10%).  An AMP-phase pseudo-slot (the Amumu Cursed Touch
precedent) adds a 10% bonus part to every damage entry while the mark is
on the target, gated by the ``r_hemoplague_debuff`` option (default on,
with the sourced R-first opening assumption).  In-game true damage is
not amplified (wiki bug note); Vladimir's kit deals none.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import AMP, SlotCtx, build_parser
from .packet_module import build_packet_module, repeat_damage_parser

PACKET_SHA256 = "03e211424b005b94fe9d0df6d90a10efc1aa4d935e306143b14b0b254bd3532d"

# Hemoplague's damage lands at the end of the infection, not at the cast:
# "infects enemies hit for 4 seconds ... After the duration, the infection
# bursts to deal magic damage to all affected targets" (data/champions.json
# Vladimir R).  The same 4 seconds is the mark's duration.
_R_INFECTION_SECONDS = 4.0

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Vladimir",
    PACKET_SHA256,
    assumption_overrides=(
        "Sanguine Pool prices all 4 pool ticks (Magic Damage Per Tick x 4 "
        "== Total Magic Damage) at 0.5-second intervals over 2 seconds.",
    ),
    # Q "drains blood from the target enemy, dealing magic damage" and E's
    # nova damages an enemy "only once": one hit each, at the cast.
    single_hit_slots=frozenset({"Q", "E"}),
    packet_part_timings={"R": {"time_offset": _R_INFECTION_SECONDS}},
    slot_parsers={
        "W": repeat_damage_parser(
            attr="Magic Damage Per Tick",
            dmg_type="magic",
            count=4,
            time_offset=0.5,
            hit_interval=0.5,
            dot_duration=2.0,
        )
    },
)
PACKET_SPEC = SLOTS.packet_spec

# HARDCODED: verify on patch updates — wiki prose, not in the JSON
# leveling rows.  Hemoplague: "increasing the damage they take from all
# sources by 10%" (patch history: "Damage amplification reduced to 10%
# from 12%", duration 4 seconds).
_R_HEMOPLAGUE_INCREASE = 0.10


def _apply_hemoplague(result: dict[str, Any]) -> None:
    """Scale every part by the 10% increased-damage-taken debuff.

    Scaling each part's amount in place (instead of appending one bonus
    part) preserves the authored per-tick / per-hit timing of the
    entry's event timeline — a single appended un-timed part would
    collapse a ticked ability back to one aggregate cast event (the E2
    tick certification).
    """
    parts = result.get("parts", ())
    if not parts:
        return
    scaled = []
    for part in parts:
        amount = float(part.amount) * (1.0 + _R_HEMOPLAGUE_INCREASE)
        scaled.append(
            DamagePart(
                part.damage_type,
                amount=amount,
                count=part.count,
                hp_scaled_damage=part.hp_scaled_damage,
                crit_effectiveness=part.crit_effectiveness,
                basic_damage=part.basic_damage,
                bonus_ad_ratio=part.bonus_ad_ratio,
                dot_stack_scaled=part.dot_stack_scaled,
                time_offset=part.time_offset,
                hit_interval=part.hit_interval,
                cc_kind=part.cc_kind,
            )
        )
    result["parts"] = tuple(scaled)
    total = sum(float(part.amount) * max(1, int(part.count)) for part in scaled)
    result["total_raw"] = total
    if "damage_by_type" in result:
        result["damage_by_type"] = {
            dtype: amount * (1.0 + _R_HEMOPLAGUE_INCREASE)
            for dtype, amount in result["damage_by_type"].items()
        }


def _hemoplague_amp(ctx: SlotCtx) -> None:
    """AMP pseudo-slot: the 10% debuff amplifies every damage entry."""
    if not ctx.options.get("r_hemoplague_debuff", True):
        return
    for key in ("Q", "W", "E", "R"):
        entry = ctx.results.get(key)
        if entry is not None:
            _apply_hemoplague(entry)


_hemoplague_amp.phase = AMP


SLOTS = dict(SLOTS)
SLOTS["hemoplague"] = _hemoplague_amp

# Sanguine Pool's ticks land on enemies who "are slowed by 40%"; Tides of
# Blood prices the fully charged nova, and "if Tides of Blood was charged
# for at least 1 second, enemies hit are also slowed for 0.5 seconds".
# Transfusion only drains.  Hemoplague controls nothing — it "increas[es]
# the damage they take from all sources by 10%" and bursts for damage.  P
# is the AP/health conversion and ``hemoplague`` is the AMP pseudo-slot;
# neither emits a cast.
MODULE_CC = {"Q": "none", "W": "slow", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Vladimir", cc_kinds=MODULE_CC)

OPTIONS = list(OPTIONS) + [
    {
        "key": "r_hemoplague_debuff",
        "type": "bool",
        "default": True,
        "label": (
            "Hemoplague mark active: the target takes 10% increased "
            "damage from all sources while marked (R-first opening)"
        ),
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Hemoplague) marks the target for 4 seconds: all damage dealt "
    "while marked is increased by 10% (cached R prose; patch history "
    "'reduced to 10% from 12%').  The AMP pseudo-slot adds the sourced "
    "10% bonus part to every damage entry (Q/W/E/R), so the R "
    "detonation itself prices 165/275/385 (+ 77% AP) — the wiki's "
    "explicit self-amplified note.  The mark is assumed applied at "
    "fight start (R-first opening) so the whole one-rotation window "
    "sits inside the 4s mark; toggle r_hemoplague_debuff off to price "
    "an unmarked rotation.  In-game true damage is not amplified "
    "(wiki bug note); Vladimir's kit deals none.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Vladimir")
