"""Anivia — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Flash Frost) must read "Total Magic Damage" (pass-through +
  detonation combined) — an attribute override, not a classifier pick.
- E (Frostbite) must read "Enhanced Damage" (target assumed Chilled).
- R (Glacial Storm) is a two-phase toggle DoT: the first 1.5 s (3 ticks
  at 0.5 s) deal the initial per-tick damage, everything after deals the
  empowered value. Duration comes from the ``r_duration`` option
  (default 5 s, floored at 1.5 s so the initial phase always completes),
  and the cooldown is pinned to 999 s so the fight engine casts it
  exactly once per fight.
- W (utility wall) deals no damage — see the Roadmap session note below.
- P (Rebirth) is never cast, so it is absent from the slot map;
  ``starting_revive_defense`` below prices its revive state, which is
  why the coverage map calls P ``modeled`` through the
  ``starting_revive_defense`` channel.

Roadmap session 3 (2026-08-20): closes both of Anivia's out_of_scope slots
(P, W).

  - P (Rebirth): already fully modeled as the sourced revive state via
    ``starting_revive_defense`` below (full max health after a 6s
    resurrection on a 240s cooldown, cached passive prose) — the same
    ``StartingDefenses.revive_*`` interface Zac's Cell Division and
    Zilean's Chronoshift use (``defensive_effects.py``'s
    ``_CHAMPION_REVIVE_SOURCES``), and it is live-tested end to end
    (``tests/test_e8_support.py::test_anivia_rebirth_revives_with_sourced_full_health``).
    ``MODULE_COVERAGE`` was simply stale, still reading "out_of_scope" for
    a slot the revive kernel had already closed — the identical stale-label
    pattern Zilean's R (Chronoshift) was already corrected under in
    Roadmap session 1. Reclassified from out_of_scope to modeled; no
    behavior change. One sourced number on this same passive stays
    unmodeled and is documented rather than silently dropped: the "-40 :
    20 (based on level) bonus armor and bonus magic resistance" granted
    while resurrecting (cached P effects[1] "Per-Level Scaling" row) has
    no consumer anywhere in this engine — the survival subsystem builds
    each combatant's defensive armor/MR state once from the pre-fight
    roster snapshot and the revive transition does not feed it a
    mid-resurrection resistance delta (grepped
    ``survival/transitions.py`` and ``defensive_effects.py``'s
    ``StartingDefenses``: no ``revive_bonus_armor`` /
    ``revive_bonus_magic_resistance`` field exists), so there is nothing
    to wire it into today (Singed R's identically-unconsumed bonus
    armor/MR rider is the same pattern).
  - W (Crystallize): the cached ability's only leveling rows are Width,
    Number of ice segments, and inter-segment distances (data/
    champions.json Anivia W) — pure geometry, no damage/heal/shield
    attribute. Cross-checked against both sourced captures: the atoms
    file (data/atoms/anivia.atoms.json) records Crystallize's family as
    "stack-transform-summon-resource" with ``"damage_type": null``, and
    the game binary (data/bin/characters/anivia.bin.json,
    ``Characters/Anivia/Spells/CrystallizeAbility/Crystallize``)
    DataValues are exactly ``WallDuration``, ``WallWidth``, ``WallChunks``,
    ``ChampPushDistance``, ``NonChampPushDistance`` — a knockback wall
    with no damage field anywhere. Reclassified from out_of_scope to
    no_damage and given an explicit, user-visible zero-damage row (the
    Shen-W / Singed-P/W convention) rather than staying silently absent.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from .inputs import champion_stat, float_option
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import damage_entry, extract_named, simple_damage
from .source_receipts import load_champion_sources
from .module_contract import coverage

# Glacial Storm's own cadence: the blizzard "deal[s] magic damage every 0.5
# seconds to enemies within and slow[s] them for 1 second, refreshing every
# 0.5 seconds while they remain inside", and "increases in size over 1.5
# seconds", after which it "is empowered to deal 300% damage" (data/
# champions.json Anivia R).  Both numbers are cached, so the ticks are
# authored rather than summed onto the cast boundary.
_R_TICK_INTERVAL = 0.5
_R_GROWTH_SECONDS = 1.5


def _glacial_storm(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: three initial half-second ticks, then empowered ticks."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

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
    entry = damage_entry(
        ability.get("name", "Glacial Storm"), rank, 999.0, total, "magic"
    )
    # Every tick slows what it damages ("slowing them for 1 second,
    # refreshing every 0.5 seconds while they remain inside"), growing phase
    # and empowered alike — a fact this module does NOT declare, and not
    # because the ledger cannot see it: with the ticks authored below, a
    # ``cc_kind`` here (or a ``dot_duration``) makes Anivia the roster's
    # first ``enhanced_consume`` producer, R's chill feeding E's "Enhanced
    # Damage".  That empties the cast-dependency audit's dated
    # acknowledged-gap list, which answers recorded ruling H6 / D-88 —
    # reserved for its own slice with its own investigator receipt, not a
    # side effect of this review.
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


def _crystallize(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: knockback wall — documented zero-damage row (no_damage).

    The cached ability's leveling rows are all geometry (Width, Number of
    ice segments, inter-segment distances) — no damage/heal/shield
    attribute exists. Confirmed against both the atoms capture
    (data/atoms/anivia.atoms.json: Crystallize's "damage_type": null) and
    the game binary (data/bin/characters/anivia.bin.json's
    CrystallizeAbility DataValues: WallDuration, WallWidth, WallChunks,
    ChampPushDistance, NonChampPushDistance — no damage field).
    """
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability.get("name", "Crystallize"),
        reason=(
            "Crystallize summons a 5-second knockback wall (width and "
            "segment count scale by rank); the cached W entry carries no "
            "damage/heal/shield leveling row at all (data/champions.json "
            "Anivia W), confirmed against the atoms capture "
            "(damage_type: null) and the game binary's DataValues "
            "(WallDuration/WallWidth/WallChunks/ChampPushDistance/"
            "NonChampPushDistance — no damage field)."
        ),
    )


OPTIONS = [
    float_option(
        "r_duration",
        5.0,
        minimum=1.5,
        maximum=30,
        label="R duration (seconds)",
        step=0.5,
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
    "W (Crystallize) is a knockback wall with no sourced damage/heal/shield "
    "number (confirmed against the cached leveling, the atoms capture, and "
    "the game binary); modeled as an explicit no_damage row rather than "
    "left silently absent.",
    "P (Rebirth) is modeled as the sourced revive state: full maximum health "
    "after a 6s resurrection on a 240s cooldown (cached passive prose), "
    "wired through StartingDefenses.revive_* like Zac and Zilean. The "
    "same passive's sourced '-40 : 20 (based on level) bonus armor and "
    "bonus magic resistance' grant while resurrecting has no consumer "
    "anywhere in this engine (no revive_bonus_armor/revive_bonus_magic_"
    "resistance field exists) and stays sourced-but-unmodeled.",
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
# R, and only doubles E's damage).  R's ticks now land on their cached
# every-0.5-second beat, but their slow stays undeclared for a reason that
# is not the ledger's (see ``_glacial_storm``).
#
# Q stays UNREVIEWED regardless, so this kit keeps the coarse control-armed
# scan: its row is the cached "Total Magic Damage" of the pass-through
# (which slows) and the recast shatter (which stuns), and the cache times
# neither — the recast happens "while the ice is in flight after its cast
# time", on a flight the cache gives a speed for and no distance.  The
# shatter's stun IS sourced ("Stun Duration" 1.1 : 1.5), but one row that
# is two landings cannot certify a single hit, so a kind on it would never
# reach the event ledger.  W's wall pushes and authors no damage part.
MODULE_CC = {"E": "none"}

parse_abilities = build_parser(SLOTS, "Anivia", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Anivia")

# P emits no cast row, so the derivation would call it out_of_scope; the
# revive above is what the engine prices (2114.0 restored at level 18 with
# no items).  W is the explicit zero-damage row ``_crystallize`` authors.
MODULE_COVERAGE = coverage(no_damage="W")
COVERAGE_CHANNELS = {"P": ("starting_revive_defense",)}
