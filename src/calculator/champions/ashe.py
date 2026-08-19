"""Ashe — slot map for the archetype engine.

Why each slot is non-generic:
- P (Frost Shot) changes what an auto attack IS: crits deal no bonus
  damage, and instead crit chance converts to bonus physical damage on
  every auto (``auto_attack_override.crit_as_bonus``). Which entry
  carries the override depends on Q:
- Q (Ranger's Focus) is a BUFF-phase custom fn — no direct damage, but
  a bonus-attack-speed stat buff plus flurry autos at a modified AD
  ratio ("Total Damage Per Flurry", a per-flurry percentage). When Q is
  active (``q_active`` option, default True) and ranked, the Q entry
  carries the auto_attack_override (flurry ratio + crit-as-bonus) and
  the passive entry is display-only; otherwise the passive entry
  carries the override at the normal 1.0 AD ratio. P therefore reads
  ``ctx.results`` and must list after Q in the slot map.
- W/R are plain attribute reads.
- E (Hawkshot) is vision utility only and is absent from the slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import BUFF, SlotCtx, build_parser
from .slotlib import extract_cooldown, extract_value, simple_damage


def _rangers_focus(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: attack-speed stat buff + flurry auto_attack_override.

    Ranger's Focus is a 4-stack system: basic attacks on-attack build a
    Focus stack (cap 4) while the ability is inactive, and the ability
    can only be activated at 4 stacks.  ``q_focus_stacks`` is the
    explicit pre-stack state (0-4); ``q_active`` remains the legacy
    activation override (default True).  The active window is
    conditional on BOTH: the pre-stacked Focus must be full.
    """
    if not bool(ctx.options.get("q_active", True)):
        return None
    if int(ctx.option("q_focus_stacks")) < 4:
        return None
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    bonus_as_pct = extract_value(ability, "Bonus Attack Speed", rank)
    # Flurry AD ratio, e.g. 110 (% AD) -> 1.10.
    flurry_ratio = extract_value(ability, "Total Damage Per Flurry", rank) / 100.0

    # Apply the bonus AS to the shared stats context (BUFF phase).
    as_ratio = ctx.stats["attack_speed_ratio"]
    ctx.stats["attack_speed"] = ctx.stat("attack_speed") + as_ratio * (
        bonus_as_pct / 100.0
    )

    return {
        "name": ability.get("name", "Ranger's Focus"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "stat_buff": {
            "bonus_attack_speed": bonus_as_pct,
        },
        "auto_attack_override": {
            "ad_ratio": flurry_ratio,
            "crit_as_bonus": True,
        },
    }


_rangers_focus.phase = BUFF


def _frost_shot(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: crit-as-bonus auto override — carried here only when Q isn't."""
    ability = ctx.ability()
    if ability is None:
        return None

    entry: dict[str, Any] = {
        "name": ability.get("name", "Frost Shot"),
        "total_raw": 0.0,
        "parts": (),
        "damage_type": "physical",
    }
    if "Q" not in ctx.results:
        # Q inactive/unranked: normal autos, crit chance as bonus damage.
        entry["auto_attack_override"] = {
            "ad_ratio": 1.0,
            "crit_as_bonus": True,
        }
    return entry


OPTIONS = [
    {
        "key": "q_active",
        "type": "bool",
        "default": True,
        "label": "Ranger's Focus active",
    },
    {
        "key": "q_focus_stacks",
        "type": "int",
        "default": 4,
        "min": 0,
        "max": 4,
        "label": "Focus stacks (4 = Ranger's Focus ready)",
    },
]

ASSUMPTIONS = [
    "Q (Ranger's Focus) is a 4-stack system: basic attacks build Focus "
    "(cap 4, 4-second expiry not modeled) and the ability activates only "
    "at 4 stacks; q_focus_stacks is the explicit pre-stack state",
    "Q assumed active by default (4 pre-stacked Focus)",
    "Passive bonus damage from crit chance applied to all auto attacks",
    "W hits a single target (one arrow per enemy)",
    "E (Hawkshot) is utility only and deals no damage",
]

SLOTS = {
    "Q": _rangers_focus,
    "P": _frost_shot,
    # One arrow's worth of damage lands on the target ("Enemies can
    # intercept multiple arrows but do not take damage from any beyond the
    # first"), and the crystal arrow shatters on the champion it hits:
    # both are a single hit at the cast boundary.
    "W": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review.  W applies "Critical Slow to enemy champions hit" and
# R "stun[s] them for 1 : 3.5 (based on distance travelled) seconds".  Q
# and P are auto-attack riders that emit no ability damage of their own —
# their Frost Shot slow rides the basic attacks, which this scan does not
# read as ability control.
MODULE_CC = {"W": "slow", "R": "stun"}

parse_abilities = build_parser(SLOTS, "Ashe", cc_kinds=MODULE_CC)


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Ashe",
        "revision_id": 4015971,
        "revision_timestamp": "2026-05-08T04:11:38Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
