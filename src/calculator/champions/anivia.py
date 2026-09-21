"""Anivia: slot map for the archetype engine.

Q (Flash Frost) reads "Total Magic Damage", the pass-through and the
detonation combined, as an attribute override rather than a classifier
pick.
E (Frostbite) reads "Enhanced Damage", the target being assumed Chilled.
R (Glacial Storm) is a two-phase toggle DoT: the first 1.5s, three ticks
at 0.5s, deal the initial per-tick damage and everything after deals the
empowered value.  ``r_duration`` (default 5s) is floored at 1.5s so the
initial phase always completes, and the cooldown is pinned to 999s so
the fight casts it once.
W (Crystallize) is ``no_damage``: its only cached leveling rows are wall
geometry.
P (Rebirth) is never cast, so it is absent from the slot map;
``starting_revive_defense`` below prices the revive state and is the
channel ``MODULE_COVERAGE`` calls P modeled through.  The resurrection's
own bonus armor and magic resistance have no consumer, because the
survival subsystem builds each combatant's defenses once from the
pre-fight roster and the revive transition feeds it no delta.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value_at_rank, spell_object
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .inputs import champion_stat, float_option
from .module_helpers import no_damage_slot, ranked_slot
from .slot_cc import CC_PER_PART
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# Glacial Storm's own cadence: the blizzard "deal[s] magic damage every 0.5
# seconds to enemies within and slow[s] them for 1 second, refreshing every
# 0.5 seconds while they remain inside", and "increases in size over 1.5
# seconds", after which it "is empowered to deal 300% damage" (data/
# champions.json Anivia R).  Both numbers are cached, so the ticks are
# authored rather than summed onto the cast boundary.
_ANIVIA_R_SPELL = spell_object("Anivia", "GlacialStorm")
_R_TICK_INTERVAL = data_value_at_rank(_ANIVIA_R_SPELL, "TickRate", 1)
_R_GROWTH_SECONDS = data_value_at_rank(_ANIVIA_R_SPELL, "GrowthTime", 1)


@ranked_slot
def _glacial_storm(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: three initial half-second ticks, then empowered ticks."""

    duration = max(float(ctx.option("r_duration")), 1.5)
    total_ticks = int(duration / 0.5)
    initial_ticks = min(3, total_ticks)
    empowered_ticks = total_ticks - initial_ticks
    initial = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    empowered = extract_named(
        ability, "Empowered Damage per Tick", rank, ctx.stats, ctx.target
    )
    total = initial_ticks * initial + empowered_ticks * empowered
    entry = damage_entry(ability_name(ability), rank, 999.0, total, "magic")
    # Every tick slows what it damages ("slowing them for 1 second,
    # refreshing every 0.5 seconds while they remain inside"), growing phase
    # and empowered alike — a fact this module does NOT declare, and not
    # because the ledger cannot see it: with the ticks authored below, a
    # ``cc_kind`` here (or a ``dot_duration``) makes Anivia the roster's
    # first ``enhanced_consume`` producer, R's chill feeding E's "Enhanced
    # Damage".  That empties the cast-dependency audit's acknowledged-gap
    # list, which is a modelling change owing its own evidence rather than
    # a side effect of this review.
    parts = [
        DamagePart(
            "magic",
            initial,
            count=initial_ticks,
            time_offset=0.0,
            hit_interval=_R_TICK_INTERVAL,
        )
    ]
    if empowered_ticks:
        parts.append(
            DamagePart(
                "magic",
                empowered,
                count=empowered_ticks,
                time_offset=_R_GROWTH_SECONDS,
                hit_interval=_R_TICK_INTERVAL,
            )
        )
    entry["parts"] = tuple(parts)
    return entry


# W: knockback wall — documented zero-damage row (no_damage).
#
# The cached ability's leveling rows are all geometry (Width, Number of
# ice segments, inter-segment distances) — no damage/heal/shield
# attribute exists. Confirmed against both the atoms capture
# (data/atoms/anivia.atoms.json: Crystallize's "damage_type": null) and
# the game binary (data/bin/characters/anivia.bin.json's
# CrystallizeAbility DataValues: WallDuration, WallWidth, WallChunks,
# ChampPushDistance, NonChampPushDistance — no damage field).
_crystallize = no_damage_slot(
    "Crystallize summons a 5-second knockback wall (width and "
    "segment count scale by rank); the cached W entry carries no "
    "damage/heal/shield leveling row at all (data/champions.json "
    "Anivia W), confirmed against the atoms capture "
    "(damage_type: null) and the game binary's DataValues "
    "(WallDuration/WallWidth/WallChunks/ChampPushDistance/"
    "NonChampPushDistance — no damage field)."
)


OPTIONS = [
    float_option(
        "r_duration",
        5.0,
        minimum=1.5,
        maximum=30,
        label="R duration (seconds)",
        step=0.5,
        rotation={"role": "self_state", "slot": "R"},
    ),
]

# E8d: sourced Rebirth revive values.  The cached passive prose (data/
# champions.json, Anivia P Rebirth) is the authoritative source: "Periodically,
# upon taking fatal damage, Anivia enters resurrection for 6 seconds and
# restores all of her health. ... If Anivia remains alive by the end of the
# duration, she is revived with her current health."  The CDragon live-game
# description agrees ("reborn with full health").  The engine's revive state
# transition consumes ``StartingDefenses.revive_*`` fields, so the module
# exposes the sourced revive contract here and the shared defense resolver
# wires it in per champion.
REVIVE_DELAY_SECONDS = 6.0
REVIVE_COOLDOWN_SECONDS = 240.0
REVIVE_MAX_HEALTH_RATIO = 1.0  # "restores all of her health"


def starting_revive_defense(level: int, stats: dict[str, float]) -> dict[str, float]:
    """Return Anivia's sourced Rebirth revive fields for StartingDefenses.

    The passive revives with full maximum health after the six-second
    resurrection window on the cached 240-second cooldown.
    """
    return {
        "revive_health_amount": float(champion_stat(stats, "health"))
        * REVIVE_MAX_HEALTH_RATIO,
        "revive_delay": REVIVE_DELAY_SECONDS,
        "revive_cooldown": REVIVE_COOLDOWN_SECONDS,
    }


ASSUMPTIONS = [
    "Q hits both pass-through and detonation (total damage used)",
    "E target is always Chilled (empowered damage used)",
    "R first 1.5s uses initial tick damage, remaining uses fully-formed tick damage",
    "W (Crystallize) is a knockback wall with no sourced damage, heal or shield row "
    "in cache, atoms or binary: no_damage.",
    "P (Rebirth) revives at full maximum health after 6s on a 240s cooldown (cached "
    "passive prose), through StartingDefenses.",
    "Its -40 to 20 by level bonus armor and magic resist while resurrecting has no "
    "consumer here and stays unmodeled.",
]

SLOTS = {
    "Q": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "W": _crystallize,
    # One targeted blast, no travel or tick phase in the cached packet.
    "E": simple_damage(
        attr="Enhanced Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _glacial_storm,
}

# Cached kit review.  E "blasts a freezing wind at the target enemy that
# deals magic damage" and applies nothing else (Chilled comes from Q and
# R, and only doubles E's damage).
#
# Q and R both name themselves per-part and neither part states a kind.
# Q's row is the cached "Total Magic Damage" of the pass-through (which
# slows) and the recast shatter (which stuns), and the cache times
# neither — the recast happens "while the ice is in flight after its cast
# time", on a flight the cache gives a speed for and no distance.  R's
# ticks land on their cached every-0.5-second beat and every one of them
# slows, but stating it here would make the ``enhanced_consume`` claim
# (see ``_glacial_storm``).  W's wall "knock[s] all units
# away from it" and authors no damage part.
MODULE_CC = {"E": "none", "Q": CC_PER_PART, "W": "knockback", "R": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Anivia", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Anivia")

# P emits no cast row, so the derivation would call it out_of_scope; the
# revive above is what the engine prices (2114.0 restored at level 18 with
# no items).  W is the explicit zero-damage row ``_crystallize`` authors.
MODULE_COVERAGE = coverage(no_damage="W")
COVERAGE_CHANNELS = {"P": ("starting_revive_defense",)}
