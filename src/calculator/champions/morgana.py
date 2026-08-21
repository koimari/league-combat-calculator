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
  dealt by her abilities (authored by this module's
  ``derive_self_healing`` rule); the passive slot itself stays a zero-damage row.

Q (Dark Binding) packet is a correct single-instance read.  E (Black
Shield) deals no damage but is ``modeled``: the ally-support scanner prices
its cached "Magic Shield Strength" row (320.0 to the target ally at rank 5,
0 AP).  The ledger absorbs it as an ordinary pool — the magic-only
restriction and the crowd-control immunity it carries are the boundary.

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
Q/Q2/W/E/R).  Coverage for P is declared through
``COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}`` rather than a
hand-written MODULE_COVERAGE table.
"""

from functools import partial
from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    with_control,
)

from ..healing_helpers import HealAnchor, _heal_from_damage, _payments

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
    # The two hits apply two different controls — the shackling slows by
    # 20% for the tether, and only the unbroken tether "become[s] stunned
    # for a duration" — so R's kinds are per part rather than per slot
    # and are authored here instead of in MODULE_CC.
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
    """P: self-heal passive — no enemy damage (this module authors it)."""
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
            "damage dealt by her abilities (authored by this module's "
            "derive_self_healing rule); the passive "
            "itself deals no enemy damage."
        ),
    }


PACKET_SHA256 = "5cc8fcb312de2d1d31c8b63157dac32a85424fa0decca7a8f1ac4ac94d689a9d"


# Cached kit review: Q's sphere damages the first enemy hit "and root[s]
# them for a duration"; W's desecrated soil only damages.  R applies two
# controls, one per part, and declares them on its parts
# (``_soul_shackles``).  E shields an ally and P heals Morgana.
MODULE_CC = {"Q": "root", "W": "none", "R": CC_PER_PART}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Morgana",
    PACKET_SHA256,
    # Dark Binding's sphere deals its packet once, to the first enemy it
    # hits, at the cast — the boundary claim that carries MODULE_CC's
    # reviewed answer for Q into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={
        "W": _tormented_shadow,
        "R": _soul_shackles,
        "P": _soul_siphon,
    },
    # The sphere's sourced Root Duration row carries MODULE_CC's reviewed
    # kind and its control atom onto the packet's Q entry.
    slot_wrappers={
        "Q": partial(with_control, duration_attr="Root Duration"),
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Tormented Shadow) prices all 10 storm ticks (Maximum Damage Per "
    "Tick x10 == Maximum Total Damage 180-700 + 200% AP) at 0.5-second "
    "intervals over the 5-second desecrated area, first tick on-cast.",
    "R (Soul Shackles) prices the initial hit plus the same magic damage "
    "again at the 3-second tether break (Magic Damage x2 == Total Magic "
    "Damage 400-700 + 160% AP); the slow/root and reveal are "
    "crowd-control utility not priced as damage.",
    "P (Soul Siphon) heals Morgana for 18% of the post-mitigation "
    "damage dealt by her abilities against champions (this "
    "module's derive_self_healing rule); the passive deals no enemy damage "
    "itself.",
    "E (Black Shield) emits the selected recipient's magic shield from the "
    "typed Magic Shield Strength atom. Its typed active-duration atom keeps "
    "crowd control from adding action downtime while the shield holds.",
    "P (Soul Siphon) has no enemy-damage formula anywhere in the cached "
    "packet; it emits a sourced zero-damage row (MODULE_COVERAGE: "
    "no_damage, not out_of_scope). P is not a cast slot in this engine's "
    "rotation.",
]
COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Soul Siphon pays 18% of every damaging ability hit.

    "heals herself for 18% of the post-mitigation damage dealt by her
    abilities against champions, large minions, and medium and large
    monsters" (wiki P).  In a champion duel every Q/W/R damage event is
    ability damage against the champion target (W's storm ticks included);
    E is a shield and deals no damage.  The anchor is the damaging hit, so
    the rule takes its occasions from ``_payments`` rather than counting
    ledger rows.
    """
    healing: list[dict] = []
    for payment in _payments(
        HealAnchor.DAMAGING_HIT,
        lambda source: source in {"Q", "W", "R"},
        damage_events,
    ):
        _heal_from_damage(
            healing,
            payment.event,
            0.18 * max(0.0, float(payment.event.get("damage", 0.0))),
            "Soul Siphon",
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Morgana", derive_self_healing)
