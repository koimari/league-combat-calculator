"""Nami — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Tidecaller's Blessing) prices 3 empowered hits
(this module's packet timing declaration).

E8d ally-support: W (Ebb and Flow) heals the selected teammate.  The event is
authored by the engine's ally-support scanner from the cached W leveling
(Heal 55-155 + 40% AP; scope one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.

Coverage: P (Surging Tides) grants movement speed to allies Nami's
abilities touch. Movement speed is an axis the engine does not have, so
the slot is out of scope.

Wave-2 ally support: the scanner also emits Ebb and Flow's
RETURN BOUNCE as a second heal packet on the same cast ("each bounce
modifying the effectiveness of the next by -20% (+ 15% per 100 AP)" of the
original, never below the sourced Minimum Heal row — the second bounce
keeps 60% + 30% per 100 AP, which is exactly the Minimum Heal row at 0 AP).
Cast on the selected teammate, the stream bounces to the enemy and back to
the same teammate in a two-champion lane (the cached notes allow the final
bounce to re-target an already-affected champion), so the return-bounce
packet uses the same one_teammate scope with its own selection key
(``heal:W:<cast>:bounce``).

P (Surging Tides) grants nearby allies bonus movement speed after Nami
casts an ability — pure ally-utility state, no enemy-damage formula
anywhere in the cached packet. The pinned packet already declares P
``kind: "no_damage"`` (a sourced zero-damage row), so it was never an
enemy-damage gap; MODULE_COVERAGE was simply stale, still reading
"out_of_scope" for an already-covered passive. Roadmap session 4 batch
D (2026-08-21) reclassifies P to "no_damage" (the Cassiopeia/Cho'Gath/
Jarvan precedent) — a documentation-only fix with zero fight-
computation change. P is not a cast slot in this engine
(``rotation_resolver`` only schedules Q/Q2/W/E/R).
"""

from typing import Any

from .. import healing_helpers as _healing
from .healing_contract import self_healing_rule
from .inputs import champion_stat
from .module_contract import coverage
from .packet_module import build_packet_module
from .slotlib import extract_named

PACKET_SHA256 = "2590188ce529af2e9f91b00238597c2b85f6f388447f0e0f4f34f6e9c4b692f3"

# Cached kit review.  Q's bubble deals magic damage "and suspend[s] them for
# 1.5 seconds" — a suspension, the Wiki's airborne class, and the kind is not
# narrowed further because the cached text never says knock up or back.  W
# "deals magic damage to enemies" and applies nothing.  E empowers three
# attacks/abilities that "each deal bonus magic damage and slow enemies for 1
# second".  R deals magic damage while "knocking them up for 0.5 seconds, and
# slowing them by 70%" — the knock-up is the immobilize the slow rides with.
# P is absent: Surging Tides only grants allies movement speed and damages
# nothing, so no event of its own could carry an answer.
MODULE_CC = {"Q": "airborne", "W": "none", "E": "slow", "R": "knockup"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nami",
    PACKET_SHA256,
    packet_tick_fixes={
        "Tidecaller's Blessing": {
            "count": 3,
            "first_tick": 0.5,
            "tick_interval": 1.0,
        }
    },
    # Aqua Prison's bubble, Ebb and Flow's stream and Tidal Wave's crest each
    # deal their packet once, at the cast — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.  E already authors
    # its own three-tick timing above.
    single_hit_slots=frozenset({"Q", "W", "R"}),
    cc_kinds=MODULE_CC,
    assumption_overrides=(
        "W (Ebb and Flow) emits two ally heal packets per cast on the "
        "selected teammate: the sourced Heal row (55-155 + 40% AP) and the "
        "return bounce at 60% + 30% per 100 AP of the original, never below "
        "the sourced Minimum Heal row (93 + 24% AP at rank 5) — the cached "
        "prose reduces each bounce by -20% (+ 15% per 100 AP) of the "
        "original, and the Minimum row is exactly 60% of the Heal row at "
        "every rank.  The bounce damage against the enemy keeps the module's "
        "full Magic Damage row (the first-bounce reduction of the damage "
        "half is not separately priced).",
        "P (Surging Tides) grants nearby allies bonus movement speed after "
        "an ability cast; it is pure ally-utility state with no enemy "
        "damage, so it emits the packet's sourced zero-damage row "
        "(MODULE_COVERAGE: no_damage, not out_of_scope). P is not a cast "
        "slot in this engine's rotation.",
    ),
)
MODULE_COVERAGE = coverage(no_damage="P")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Nami self-healing events from its authored packet."""
    healing = []
    w_rank = _healing.parsed_rank(ability_damages, "W")
    w_ability = _healing.ability_json(champion_data, "W")
    base = extract_named(w_ability, "Heal", w_rank, champion_stats, {})
    floor = extract_named(w_ability, "Minimum Heal", w_rank, champion_stats, {})
    ap = champion_stat(champion_stats, "ability_power")
    amount = max(floor, base * (0.80 + 0.15 * ap / 100.0))
    for payment in _healing.payments(
        _healing.HealAnchor.CAST, "W", damage_events, cast_timeline
    ):
        event = payment.event
        _healing.heal_from_damage(
            healing, event, amount, "Ebb and Flow", link_to_damage=False
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Nami")(derive_self_healing)
