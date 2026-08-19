"""Aurora — slot map for the archetype engine.

Why each slot is non-generic:
- P (Spirit Abjuration) is a custom fn: a %maxHP proc whose PERCENT
  itself scales with AP (1% + 2.7% per 100 AP), which the shared
  ``pct_health_per_hit`` math cannot express and the JSON does not carry
  (the parser only captured the MONSTER damage cap as attribute
  "Bonus Damage"), so the formula lives as module constants. Aurora's
  stack counter advances on damaging basic attacks AND damaging ability
  hits, so the emitted on-hit dict carries ``count_ability_hits`` — the
  fight engine adds the rotation's damaging ability hits to the auto
  count before dividing by ``stacks_required``. The passive's
  healing/Spirit component deals no enemy damage and is skipped.
- Q (Twofold Hex) is a custom fn: the first cast and the auto-recast
  (expunge) are two DamageParts of one entry, so the recast fires
  exactly once per cast by construction. The recast scales with the
  target's MISSING health from "Minimum Magic Damage" (full HP) to
  "Maximum Magic Damage" (zero HP); an ``hp_scaled_damage`` closure
  lets the fight engine evaluate it against the tracked target HP at
  recast time (BotRK-style decreasing-HP model).
- W (Across the Veil) is a dash/invisibility/MS utility with zero
  damage (JSON damageType is None) — not modeled, absent from the slot
  map. It applies no passive stack either.
- E (The Weirding) and R (Between Worlds) are generic
  ``simple_damage`` reads; the slow / rift zone / Realm Hopper effects
  are utility and not modeled.
"""

from typing import Any, Callable

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)

# HARDCODED: verify on patch updates — the wiki JSON only carries the
# passive's monster damage cap (attribute "Bonus Damage", 100-270 by
# level); the champion-target formula is wiki prose:
# https://wiki.leagueoflegends.com/en-us/Aurora
# Spirit Abjuration: on the 3rd stack, all stacks consume dealing bonus
# magic damage equal to 1% (+ 2.7% per 100 AP) of the target's MAX health.
_SPIRIT_STACKS = 3
_SPIRIT_PCT_BASE = 1.0  # % of target max health
_SPIRIT_PCT_PER_100_AP = 2.7  # additional % per 100 AP


def _spirit_abjuration(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: every-3rd-hit %maxHP magic proc; autos AND ability hits stack."""
    ability = ctx.ability()
    if ability is None:
        return None

    ap = ctx.stat("ability_power")
    percent = _SPIRIT_PCT_BASE + _SPIRIT_PCT_PER_100_AP * ap / 100.0
    per_proc = percent / 100.0 * ctx.target_stat("target_max_health")

    name = ability.get("name", "Spirit Abjuration")
    return ability_on_hit_entry(
        name,
        ctx.level,
        "magic",
        {
            "name": name,
            "damage_per_hit": per_proc / _SPIRIT_STACKS,
            "damage_type": "magic",
            "stacks_required": _SPIRIT_STACKS,
            # Damaging ability hits advance the stack counter alongside
            # autos — the fight engine adds the rotation's hits.
            "count_ability_hits": True,
        },
    )


_spirit_abjuration.phase = ONHIT


def _expunge_scaled(recast_min: float, recast_max: float) -> Callable[[float], float]:
    """Q recast damage: linear min -> max on the missing-HP fraction."""

    def scaled(missing_ratio: float) -> float:
        return recast_min + (recast_max - recast_min) * missing_ratio

    return scaled


def _twofold_hex(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: first-cast bolts + auto-recast expunge, both fire every cast."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    first = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    recast_min = extract_named(
        ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target
    )
    recast_max = extract_named(
        ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target
    )

    # "Subsequent Bolt Minimum/Maximum Magic Damage" (effects[2]) are
    # deliberately NOT read: those are the 20%-damage bolts pulled
    # through OTHER marked enemies — this is a single-target calc, the
    # primary target never takes them. Do not "fix" this by adding them.
    entry = damage_entry(
        ability.get("name", "Twofold Hex"),
        rank,
        extract_cooldown(ability, rank),
        first + recast_min,  # full-HP bound (hp-scaled entries store a bound)
        "magic",
    )
    entry["parts"] = (
        # The recast is available after 0.1 seconds; retaining that sourced
        # delay matters for Spirit Abjuration's per-hit stack order.
        DamagePart("magic", first, time_offset=0.0),
        DamagePart(
            "magic",
            amount=recast_min,  # static diagnostic; the engine uses the closure
            hp_scaled_damage=_expunge_scaled(recast_min, recast_max),
            time_offset=0.1,
        ),
    )
    return entry


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Passive procs every 3rd damaging hit; autos AND damaging ability "
    "hits (Q first cast, Q recast, E, R) all count stacks",
    "Passive damage is % of target max health with AP-scaled percent "
    "(1% + 2.7% per 100 AP) — wiki prose; the JSON only carries the "
    "monster cap",
    "Passive healing/Spirits not modeled (no enemy damage)",
    "Q recast always fires once per Q cast (auto-recast at mark end)",
    "Q recast missing-HP scaling evaluated against the fight sim's "
    "tracked target HP (BotRK-style decreasing-HP model)",
    "Q subsequent bolts (20% to other marked enemies) not modeled — "
    "single-target calc",
    "W (Across the Veil) is utility only (dash/invisibility/MS) — not modeled",
    "R rift zone / slows are utility — only the leap damage is modeled",
]

SLOTS = {
    "P": _spirit_abjuration,
    "Q": _twofold_hex,
    # E's blast and R's shockwave each land once on the target they damage,
    # with no sourced sub-cast phase in the cached packet.
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review.  E "slows them by 80% for 1 second" and R's shockwave
# "slow[s] them by 30% for 2 seconds".  Q only "marks them with a curse",
# which is a mark the recast expunges, not crowd control.  W deals no
# damage and P is an on-hit stack consume.
MODULE_CC = {"Q": "none", "E": "slow", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Aurora", cc_kinds=MODULE_CC)


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Aurora",
        "revision_id": 3959795,
        "revision_timestamp": "2025-10-17T02:11:19Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
