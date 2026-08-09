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

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Vladimir",
    PACKET_SHA256,
    assumption_overrides=(
        "Sanguine Pool prices all 4 pool ticks (Magic Damage Per Tick x 4 "
        "== Total Magic Damage) at 0.5-second intervals over 2 seconds.",
    ),
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
parse_abilities = build_parser(SLOTS, "Vladimir")

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
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Vladimir self-healing events from its authored packet."""
    healing = []
    q_rank = _healing._rank(ability_damages, "Q")
    q_heal = _healing.extract_named(
        _healing._ability(champion_data, "Q"), "Heal", q_rank, champion_stats
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "Q"
    ):
        _healing._heal_from_damage(
            healing, event, q_heal, "Transfusion", link_to_damage=False
        )
    # Sanguine Pool (W): heals for 30% of pre-mitigation damage dealt
    # (patch 12.13: "Healing increased to 30% of damage dealt from 15%";
    # 18% against minions — champion targets assumed here).
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "W"
    ):
        # Pre-mitigation damage per the wiki ("30% of the pre-mitigation
        # damage dealt"); the engine exposes it as event["raw_damage"].
        dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
        _healing._heal_from_damage(healing, event, 0.30 * dealt, "Sanguine Pool")
    # Hemoplague (R): flat heal per infected champion, reduced for later
    # targets (wiki: "Heal: 150 / 250 / 350 (+ 70% AP)" and
    # "Reduced Heal: 60 / 100 / 140 (+ 28% AP)").  Each pair fight sees
    # only its own R packet, so every copy is authored at the full value
    # with the reduced amount attached as an explicit receipt; the
    # coupled participant ledger re-prices later roster targets so the
    # first infected champion pays the full heal and each additional
    # champion pays the reduced heal.
    r_rank = _healing._rank(ability_damages, "R")
    r_heal = _healing.extract_named(
        _healing._ability(champion_data, "R"), "Heal", r_rank, champion_stats
    )
    r_reduced = _healing.extract_named(
        _healing._ability(champion_data, "R"), "Reduced Heal", r_rank, champion_stats
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        _healing._heal_from_damage(
            healing,
            event,
            r_heal,
            "Hemoplague",
            later_target_amount=r_reduced,
            link_to_damage=False,
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Vladimir", derive_self_healing)
