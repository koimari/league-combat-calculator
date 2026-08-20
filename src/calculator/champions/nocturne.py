"""Nocturne — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Unspeakable Horror) prices 4 sourced 0.5s tether ticks
(this module's packet timing declaration).

W (Shroud of Darkness) is two grants under one slot.  Its *passive*
half — "Nocturne gains bonus attack speed", the cached "Bonus Attack
Speed" row (30-50%) — has no duration at all, so it rides a BUFF-phase
``stat_buff`` at full value whenever W is ranked.  Its active half only
doubles that row to "Enhanced Bonus Attack Speed" (60-100%) for 5
seconds "upon successfully blocking a hostile effect", which a damage
package does not imply: the ``w_spellshield_block`` option arms it, and
only the difference between the two rows is time-weighted onto the
5-second window.
"""

from functools import partial
from typing import Any

from .engine import BUFF, SlotCtx
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    damage_entry,
    extract_cooldown,
    extract_value,
    with_item_on_hits,
)

PACKET_SHA256 = "0ce5c515d925ee81726b3430bfa9068b01a64a9901b67361a7f8da766fd561b8"

# HARDCODED: verify on patch updates — the enhanced window is cached W
# prose ("Shroud of Darkness' bonus attack speed is doubled for 5
# seconds"); both percentages are JSON leveling rows.
_W_ENHANCED_SECONDS = 5.0


def _shroud_of_darkness(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the permanent 30-50% attack speed, doubled on a blocked cast."""
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    passive_as = extract_value(ability, "Bonus Attack Speed", rank)
    enhanced_as = extract_value(ability, "Enhanced Bonus Attack Speed", rank)
    blocked = bool(ctx.option("w_spellshield_block"))
    share = buff_window_share(ctx, _W_ENHANCED_SECONDS) if blocked else 0.0
    bonus_as = passive_as + (enhanced_as - passive_as) * share
    entry = damage_entry(
        ability.get("name", "Shroud of Darkness"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{passive_as:g}% bonus attack speed (the passive half, no "
        f"duration); a successful spell-shield block doubles it to "
        f"+{enhanced_as:g}% for {_W_ENHANCED_SECONDS:g}s "
        f"({'armed' if blocked else 'not armed'}: {bonus_as:g}% applied)"
    )
    return entry


_shroud_of_darkness.phase = BUFF


# Cached kit review.  Q's shadow blade only "deal[s] physical damage to
# enemies hit" — its one "slow" word is the dusk trail "slowly
# disappear[ing]", not a slow applied to anyone.  E's tether ticks for
# magic damage and, unbroken, "the target is feared for a duration while
# being slowed by 90%": the fear is the immobilize the slow rides with.  R
# nearsights, which is not an immobilize and has no kind in the vocabulary
# (the Graves W reading), and its damaging recast dash applies nothing.
# W (spell shield) deals no damage, and P is absent because Umbra Blades is
# an on-hit rider on the auto stream rather than an ability event.
MODULE_CC = {"Q": "none", "E": "fear", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nocturne",
    PACKET_SHA256,
    packet_tick_fixes={
        "Unspeakable Horror": {
            "count": 4,
            "first_tick": 0.5,
            "tick_interval": 0.5,
            "dot_duration": 2.0,
        }
    },
    # Duskbringer's blade hits each enemy in its line once and Paranoia's
    # recast dash damages once on arrival — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.  E already
    # authors its own four-tick tether timing above.
    single_hit_slots=frozenset({"Q", "R"}),
    slot_parsers={
        "W": _shroud_of_darkness,
    },
    slot_wrappers={
        "P": partial(
            with_item_on_hits, effectiveness=1.0, hits=1, triggers=("on_hit",)
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "w_spellshield_block",
        "type": "bool",
        "default": False,
        "label": "Shroud of Darkness blocked a hostile spell (doubles its AS)",
        "rotation": {
            "role": "self_state",
            "slot": "W",
            "note": (
                "Arms W's own doubled attack speed; the block is state the "
                "enemy creates, not a cross-slot cast edge."
            ),
        },
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Shroud of Darkness) grants its passive Bonus Attack Speed row "
    "(30-50%) unconditionally — the cached text gives that half no "
    "duration — and the fight engine applies it to the auto count.",
    "The active's doubled Enhanced Bonus Attack Speed row (60-100%) is "
    "opt-in through w_spellshield_block: it needs an enemy cast for the "
    "spell shield to block, which a damage package does not imply.  When "
    "armed, only the difference between the two rows is time-weighted "
    "over the sourced 5-second window.",
]

# No MODULE_COVERAGE: every one of the five slots emits a priced row now.
