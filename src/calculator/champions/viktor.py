"""Viktor: full-entry-reviewed packet module.

R (Arcane Storm) prices the impact plus the full 6.5-second storm, its "Magic
Damage" row and six per-tick rows summing to the cached total.
Q (Siphon Power) carries the sourced self-shield: the per-level "Bonus Damage"
row is the shield base, not damage, the cache mislabelling it, and it rides the
Q damage entry as a ``self_shield_events`` payload.  Q's Discharge empowered
attack is priced from the "Modified Magic Damage" row as an on-hit capped at one
application inside the 4-second window, gated by ``q_discharge``; the "Total
Magic Damage" row is the projectile and discharge summed and is never read.
W (Gravity Field) is ``no_damage``, but its sourced slow IS priced:
``with_control_event`` publishes the cached "Slow" row against the slot's prose
control duration.  Only the fifth-stack stun stays unpriced, having no atom.
P (Glorious Evolution) stays ``out_of_scope``.  Its augments really do change
what the other slots do, they are bought with Hex Fragments earned across a
whole game, and the cached entry has no leveling row anywhere, so pricing one
would mean inventing both the fragment count and the effect.
"""

from typing import Any

from ..binary_roots import data_value, spell_object
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .packet_module import build_packet_module, first_plus_repeats_parser
from .shared_mechanics import per_level_row
from .slot_control import with_control_event
from .slot_entries import attach_self_shield
from .slot_extract import extract_named

# HARDCODED: verify on patch updates — the shield window (2.5s) and the
# Discharge window (4s) are wiki Q prose; the shield base row and the
# discharge damage are cached leveling rows read live below.
# ROOTED IN THE BINARY (ViktorQ.BuffDuration); the wiki Q prose
# corroborates the window.
_Q_SHIELD_DURATION_SECONDS = data_value(
    spell_object("Viktor", "ViktorQ"), "BuffDuration"
)

PACKET_SHA256 = "542116107f7a930a0dbae3ed0dfb602d84d0b90cb6bf86f2b4832bae1c8ad13f"


def _siphon_shield(ctx: SlotCtx) -> float:
    """Q's shield: per-LEVEL base (40 : 140, 18 cached values) + 25% AP;
    the long row reads at the level.
    """
    return per_level_row(
        ctx,
        "Bonus Damage",
        champion="Viktor",
        stop="Viktor Q shield leveling row is unavailable",
    )


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
        if bool(ctx.option("q_discharge")):
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
# an interrupt ``control_spec``'s kind vocabulary has no word for and no
# control-armed item passive keys on; and the W augment Magnetize would
# make "Viktor's other abilities ... slow enemies hit by 20%", which the
# Hex Fragment augments (out of scope here) are the only way to buy.
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "none", "P": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Viktor",
    PACKET_SHA256,
    assumption_overrides=(
        "Arcane Storm prices the impact plus the full 6.5-second storm.",
        "That is Magic Damage + 6 x Magic Damage Per Tick == Total Magic Damage.",
    ),
    # One beam, one hit: "fires an energy beam along the target path that
    # deals magic damage to enemies hit" — the packet has no travel or tick
    # phase to place, so the hit lands at the cast.  Q is one projectile hit
    # at the same boundary, and certifying it is what carries the
    # module-authored self-shield payload onto the event row.
    single_hit_slots=frozenset({"E", "Q"}),
    slot_parsers={
        "R": first_plus_repeats_parser(
            first_attr="Magic Damage",
            repeat_attr="Magic Damage Per Tick",
            repeats=6,
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

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Siphon Power) shields Viktor for the per-level 40 to 140 + 25% AP for 2.5 "
    "seconds.",
    "The cache's 'Bonus Damage' row is the shield base, level-indexed; the cast "
    "grants it as a self_shield_events payload.",
    "Q's Discharge empowers the next basic attack for 4 seconds.",
    "The Modified Magic Damage row, 20 to 120 by rank + 100% AD + 50% AP, is a "
    "one-application on-hit.",
    "q_discharge defaults True; the Total Magic Damage row is the projectile plus "
    "discharge sum.",
    "W (Gravity Field) crowd control and P (Glorious Evolution) augments "
    "remain documented out of scope.",
]
OPTIONS.append(
    {
        "key": "q_discharge",
        "type": "bool",
        "default": True,
        "label": "Q Discharge empowered next basic attack",
        "rotation": {"role": "self_state", "slot": "Q"},
    }
)
MODULE_COVERAGE = coverage(out_of_scope="P", no_damage="W")
