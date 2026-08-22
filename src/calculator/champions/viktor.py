"""Viktor — CP10.9 full-entry-reviewed packet module.

E2 fix (packet_module): R (Arcane Storm) prices the impact plus the full
6.5-second storm (Magic Damage + 6 x Magic Damage Per Tick == Total
Magic Damage).

P1-2 fixes:
- Q (Siphon Power) now carries the sourced self-shield: the per-level
  "Bonus Damage" row is the shield base (40 : 140 by level + 25% AP)
  for 2.5 seconds (wiki Q effect prose; the row is mislabelled "Bonus
  Damage" in the cache, and its 18 values are level-indexed), authored
  via the E8c ``self_shield_events`` payload on the Q damage entry.
- Q's Discharge empowered-auto on-hit is priced from the "Modified
  Magic Damage" row (20 : 120 by rank + 100% AD + 50% AP) as an
  on-hit payload capped at one application (the next basic attack
  within the 4-second Discharge window), gated by the ``q_discharge``
  option (default True).  The "Total Magic Damage" row is the
  projectile + discharge sum and is not read separately.

Coverage: P (Glorious Evolution) spends Hex Fragments on augments that
change how the other abilities behave, and W (Gravity Field) slows and
then stuns on the fifth stack. Transform and CC magnitude are axes the
engine does not have, so both slots are out of scope.
"""

from typing import Any

from .engine import SlotCtx
from .packet_module import build_packet_module, initial_plus_ticks_parser
from .slotlib import (
    attach_self_shield,
    extract_named,
    find_named_leveling,
    is_flat_unit,
    resolve_scaling,
    with_control_event,
)
from .module_contract import coverage

# HARDCODED: verify on patch updates — the shield window (2.5s) and the
# Discharge window (4s) are wiki Q prose; the shield base row and the
# discharge damage are cached leveling rows read live below.
_Q_SHIELD_DURATION_SECONDS = 2.5

PACKET_SHA256 = "542116107f7a930a0dbae3ed0dfb602d84d0b90cb6bf86f2b4832bae1c8ad13f"


def _siphon_shield(ctx: SlotCtx) -> float:
    """Q's shield: per-LEVEL base (40 : 140, 18 cached values) + 25% AP.

    ``extract_named`` indexes the 18-value row by RANK (values[4] at
    rank 5), but the wiki prose is "40 : 140 (based on level)"; long
    arrays (>= 18 values) are level-indexed here, the Ambessa W
    convention.
    """
    ability = ctx.ability()
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, "Bonus Damage")
    if leveling is None:
        raise ValueError("Viktor Q shield leveling row is unavailable")
    total = 0.0
    rank = ctx.rank_for()
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        if len(values) >= 18:
            index = min(max(ctx.level - 1, 0), len(values) - 1)
        else:
            index = min(max(rank - 1, 0), len(values) - 1)
        value = float(values[index])
        unit = units[index] if index < len(units) else ""
        total += (
            value
            if is_flat_unit(unit)
            else resolve_scaling(unit, value, ctx.stats, ctx.target)
        )
    return total


def _siphon_power(packet_q):
    """Q: the projectile packet plus the shield and the Discharge on-hit."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_q(ctx)
        rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
        if entry is None or rank < 1:
            return entry
        shield = _siphon_shield(ctx)
        entry = attach_self_shield(
            entry,
            amount=shield,
            duration=_Q_SHIELD_DURATION_SECONDS,
            source=entry.get("name", "Siphon Power"),
            detail=(
                f"Q also shields Viktor for {shield:g} for "
                f"{_Q_SHIELD_DURATION_SECONDS:g}s (self); the Discharge "
                "empowered next basic attack is priced as a one-application "
                "on-hit"
            ),
        )
        if bool(ctx.options.get("q_discharge", True)):
            ability = ctx.ability()
            discharge = extract_named(
                ability, "Modified Magic Damage", rank, ctx.stats, ctx.target
            )
            entry["on_hit"] = {
                "name": "Siphon Power (Discharge)",
                "damage_per_hit": discharge,
                "damage_type": "magic",
                "max_procs": 1,
                "detail": (
                    "Discharge empowered next basic attack within the 4-second "
                    "window (Modified Magic Damage 20 : 120 by rank + 100% AD "
                    "+ 50% AP)"
                ),
            }
        return entry

    return parse


# Siphon Power's device and its Discharge auto only "deal[] magic damage",
# Hextech Ray's beam "deals magic damage to enemies hit and briefly grants
# sight", and Arcane Storm's impact and bolts only damage.  W (Gravity
# Field) is where this kit's slow and 5-stack stun live, and it is
# documented out_of_scope — no damage row, no reviewable marker.
#
# Two facts this declaration does not carry, both out of the module's
# modelled kit: Arcane Storm also "disrupt[s] their channeled abilities",
# an interrupt the campaign's kind vocabulary has no word for and which no
# control-armed item passive keys on; and the W augment Magnetize would
# make "Viktor's other abilities ... slow enemies hit by 20%", which the
# Hex Fragment augments (out of scope here) are the only way to buy.
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Viktor",
    PACKET_SHA256,
    assumption_overrides=(
        "Arcane Storm prices the impact plus the full 6.5-second storm "
        "(Magic Damage + 6 x Magic Damage Per Tick == Total Magic Damage).",
    ),
    # One beam, one hit: "fires an energy beam along the target path that
    # deals magic damage to enemies hit" — the packet has no travel or tick
    # phase to place, so the hit lands at the cast.  Q is one projectile hit
    # at the same boundary, and certifying it is what carries the
    # module-authored self-shield payload onto the event row.
    single_hit_slots=frozenset({"E", "Q"}),
    slot_parsers={
        "R": initial_plus_ticks_parser(
            initial_attr="Magic Damage",
            tick_attr="Magic Damage Per Tick",
            dmg_type="magic",
            tick_count=6,
            time_offset=1.0,
            hit_interval=1.0,
            dot_duration=6.5,
        )
    },
    slot_wrappers={
        "Q": _siphon_power,
        # Gravity Field prices no damage; it "activates to slow enemies
        # within for 1 second, refreshing every 0.25 seconds", which the
        # cache carries as the slot's control-duration atom (the 4.5s
        # active-duration atom is the field's own lifetime, not the
        # slow's window), and the cached "Slow" row (33/36/39/42/45%) is
        # how hard.  The fifth-stack 1.5s stun has no atom at all and
        # stays unpriced.
        "W": lambda parser: with_control_event(
            parser,
            duration_source="prose",
            magnitude_attr="Slow",
        ),
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Siphon Power) shields Viktor for the per-level 40 : 140 (+ 25% AP) "
    "for 2.5 seconds (the cache's 'Bonus Damage' row is the shield base, "
    "level-indexed); the shield is granted at the cast (E8c "
    "self_shield_events payload).",
    "Q's Discharge empowers the next basic attack for 4 seconds: the "
    "Modified Magic Damage row (20 : 120 by rank + 100% AD + 50% AP) is "
    "priced as a one-application on-hit (q_discharge, default True). "
    "The Total Magic Damage row is the projectile + discharge sum.",
    "W (Gravity Field) crowd control and P (Glorious Evolution) augments "
    "remain documented out of scope.",
]
OPTIONS.append(
    {
        "key": "q_discharge",
        "type": "bool",
        "default": True,
        "label": "Q Discharge empowered next basic attack",
    }
)
MODULE_COVERAGE = coverage(out_of_scope="PW")
