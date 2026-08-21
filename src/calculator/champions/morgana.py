"""Morgana — CP10.4 packet module with the E9-1 gap fixes.

E9-1 closes the three remaining audit gaps over the CP10.4 packet:
- W (Tormented Shadow) prices all 10 storm ticks: "Maximum Damage Per
  Tick" x 10 == "Maximum Total Damage" at every rank (the packet
  priced ONE tick).  The storm lasts 5 seconds, dealing magic damage
  "on-cast and every 0.5 seconds thereafter".
- R (Soul Shackles) prices the initial hit AND the same magic damage
  again when the 3-second tether breaks: "Total Magic Damage" == 2 x
  "Magic Damage" at every rank (the packet priced only the initial
  hit).
- P (Soul Siphon) heals Morgana for 18% of the post-mitigation damage
  dealt by her abilities (authored by the HEALING_RULE_CHAMPIONS rule
  in healing.py); the passive slot itself stays a zero-damage row.

Q (Dark Binding) packet is a correct single-instance read; E (Black
Shield) is a documented no-damage shield.

P (Soul Siphon) is the self-heal passive: no enemy-damage formula exists
anywhere in the cached packet (the pinned packet already declares P
``kind: "no_damage"``, and this module's ``_soul_siphon`` override emits
the same sourced zero-damage row so the heal rule has a P entry to
attach to). It was never an enemy-damage gap; MODULE_COVERAGE was
simply stale, still reading "out_of_scope" for an already-covered
passive. Roadmap session 4 batch D (2026-08-21) reclassifies P to
"no_damage" (the Cassiopeia/Cho'Gath/Jarvan precedent) — a
documentation-only fix with zero fight-computation change. P is not a
cast slot in this engine (``rotation_resolver`` only schedules
Q/Q2/W/E/R).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    with_control,
)

# Sourced storm cadence (wiki W): "take magic damage on-cast and every
# 0.5 seconds thereafter" over the 5-second desecrated area -> 10 ticks
# of "Maximum Damage Per Tick" == "Maximum Total Damage".
_W_TICKS = 10
_W_TICK_INTERVAL = 0.5
_W_DURATION = 5.0
# R tether length (wiki R): the second hit lands when the 3-second
# tether breaks ("If a target does not break their tether by the end of
# its duration, they are dealt the same magic damage again").
_R_TETHER_SECONDS = 3.0


def _tormented_shadow(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: 10 ticks of Maximum Damage Per Tick == Maximum Total Damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_tick = extract_named(
        ability, "Maximum Damage Per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Tormented Shadow"),
        rank,
        extract_cooldown(ability, rank),
        per_tick * _W_TICKS,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_W_TICKS,
            time_offset=0.0,
            hit_interval=_W_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _W_DURATION
    entry["detail"] = (
        f"{_W_TICKS} sourced {_W_TICK_INTERVAL:g}s-interval ticks "
        f"(Maximum Damage Per Tick x{_W_TICKS} == Maximum Total Damage)"
    )
    return entry


def _soul_shackles(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: initial hit + the same damage again at the 3s tether break."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Soul Shackles"),
        rank,
        extract_cooldown(ability, rank),
        initial * 2,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            initial,
            time_offset=0.0,
            cc_kind="slow",
        ),
        DamagePart(
            "magic",
            initial,
            time_offset=_R_TETHER_SECONDS,
            cc_kind="stun",
            cc_duration=extract_value(ability, "Stun Duration", rank),
        ),
    )
    entry["cc_reviewed"] = True
    entry["dot_duration"] = _R_TETHER_SECONDS
    entry["detail"] = (
        f"initial hit + the same {initial:.6g} magic damage at the "
        f"{_R_TETHER_SECONDS:g}s tether break (Magic Damage x2 == "
        "Total Magic Damage)"
    )
    return entry


def _soul_siphon(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: self-heal passive — no enemy damage (healing.py authors it)."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Soul Siphon"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Soul Siphon heals Morgana for 18% of the post-mitigation "
            "damage dealt by her abilities (authored by the "
            "HEALING_RULE_CHAMPIONS rule in healing.py); the passive "
            "itself deals no enemy damage."
        ),
    }


PACKET_SHA256 = "5cc8fcb312de2d1d31c8b63157dac32a85424fa0decca7a8f1ac4ac94d689a9d"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Morgana", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["Q"] = with_control(
    SLOTS["Q"],
    kind="root",
    duration_attr="Root Duration",
)
SLOTS["W"] = _tormented_shadow
SLOTS["R"] = _soul_shackles
SLOTS["P"] = _soul_siphon
parse_abilities = build_parser(SLOTS, "Morgana")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Tormented Shadow) prices all 10 storm ticks (Maximum Damage Per "
    "Tick x10 == Maximum Total Damage 180-700 + 200% AP) at 0.5-second "
    "intervals over the 5-second desecrated area, first tick on-cast.",
    "R (Soul Shackles) prices the initial hit plus the same magic damage "
    "again at the 3-second tether break (Magic Damage x2 == Total Magic "
    "Damage 400-700 + 160% AP); the slow/root and reveal are "
    "crowd-control utility not priced as damage.",
    "P (Soul Siphon) heals Morgana for 18% of the post-mitigation "
    "damage dealt by her abilities against champions (healing.py "
    "HEALING_RULE_CHAMPIONS); the passive deals no enemy damage "
    "itself.",
    "E (Black Shield) emits the selected recipient's magic shield from the "
    "typed Magic Shield Strength atom. Its typed active-duration atom keeps "
    "crowd control from adding action downtime while the shield holds.",
    "P (Soul Siphon) has no enemy-damage formula anywhere in the cached "
    "packet; it emits a sourced zero-damage row (MODULE_COVERAGE: "
    "no_damage, not out_of_scope). P is not a cast slot in this engine's "
    "rotation.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
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
    """Resolve Morgana self-healing events from its authored packet."""
    healing = []
    for event in damage_events:
        if _healing._event_source(event) not in {"Q", "W", "R"}:
            continue
        _healing._heal_from_damage(
            healing,
            event,
            0.18 * max(0.0, float(event.get("damage", 0.0))),
            "Soul Siphon",
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Morgana", derive_self_healing)
