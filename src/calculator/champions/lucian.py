"""Lucian: packet module over the double shot and the channel.

R (The Culling) prices the full 3-second channel, 22 shots of the cached
"Physical Damage Per Shot" row, the cache carrying only that row and the prose
shot count.  Its crit-chance-scaled extra shots are zero at 0% crit and are
not modeled for crit builds.
P (Lightslinger) is the engine's double-shot pattern: after an ability cast
the next basic attack within 3.5 seconds fires a second shot at 50/55/60% AD
by level band, 1 to 6, 7 to 12 and 13 to 18.  The fight prices one second shot
per basic attack the rotation fires, because in the standard weave every auto
follows a cast, and the second shot applies on-hit effects and can crit.
Q and W are single-instance reads.
E (Relentless Pursuit) is ``no_damage``: all three cached effect entries carry
empty ``leveling`` arrays and the binary's ``LucianE`` has no calculations at
all, only dash and cooldown-refund parameters.
"""

from typing import Any

from .contract_vocabulary import coverage
from .engine import SlotCtx
from .module_helpers import ability_slot, at_level, no_damage_slot
from .packet_module import build_packet_module

# HARDCODED: verify on patch updates — the second shot's AD ratio is
# level-banded.  The cached P JSON carries only the prose "50% / 55% /
# 60% (based on level) AD physical damage"; the wiki's
# Template:Data_Lucian/Lightslinger pins the breakpoints
# (data-top-values="1;7;13"): 50% at levels 1-6, 55% at 7-12, 60% at
# 13-18.
_LIGHTSLINGER_RATIO_BANDS: tuple[tuple[int, float], ...] = (
    (13, 0.60),
    (7, 0.55),
    (1, 0.50),
)


@ability_slot("P")
def _lightslinger(ctx: SlotCtx, _passive: dict[str, Any]) -> dict[str, Any] | None:
    """P: second shot after each ability — the engine double-shot path."""
    return {
        "name": "Lightslinger",
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "double_shot": {
            "name": "Lightslinger",
            "ad_ratio": at_level(_LIGHTSLINGER_RATIO_BANDS, ctx.level),
        },
    }


# All three cached E effect rows carry empty leveling (cooldown refund on
# Lightslinger hit, the dash, the attack-timer reset), and the game binary's
# LucianE record holds only non-damage DataValues.
_relentless_pursuit = no_damage_slot(
    "Active: Lucian dashes in the target direction, resetting his "
    "basic attack timer. Passive: Relentless Pursuit's current "
    "cooldown is reduced by 1s per Lightslinger shot hit (2s "
    "against champions). Pure movement/cooldown-refund state -- "
    "no leveling row and no combat-damage interaction; "
    "corroborated by the game binary's LucianE spell record, "
    "which carries no mSpellCalculations table.",
    name="Relentless Pursuit",
)


PACKET_SHA256 = "3fe0c536a453a203c13c7bb713274cbc217785ea29e4723c090c474b7607b9e6"


# Cached kit review: nothing Lucian casts applies crowd control.  Q is a
# laser, W marks its targets and grants HIM movement speed, E is a dash,
# and R is 22 shots.  (Vigilance reads an ally's immobilize; it applies
# none of its own.)
MODULE_CC = {"Q": "none", "W": "none", "R": "none", "P": "none", "E": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Lucian",
    PACKET_SHA256,
    packet_tick_fixes={
        "The Culling": {
            "count": 22,
            "first_tick": 0.0,
            "tick_interval": 0.1364,
            "dot_duration": 3.0,
        }
    },
    # Piercing Light's laser and Ardent Blaze's explosion each deal their
    # packet once, at the cast — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.
    single_hit_slots=frozenset({"Q", "W"}),
    slot_parsers={
        "P": _lightslinger,
        "E": _relentless_pursuit,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "R (The Culling) prices all 22 sourced shots of the 3s channel: the cache has a "
    "per-shot row, no total.",
    "R's crit-scaled extra shots, '+ 0 : 6 based on critical strike chance', are not "
    "modeled.",
    "P (Lightslinger) adds a second shot on the next basic attack after each cast, "
    "50/55/60% AD by level.",
    "The bands are levels 1-6, 7-12 and 13-18 from the wiki data template.",
    "One second shot is priced per basic attack the rotation fires; it applies on-hit "
    "and can crit.",
    "E (Relentless Pursuit) has no sourced damage row: all three cached effects have "
    "empty leveling.",
    "The binary's LucianE record has no mSpellCalculations, only cooldown-refund and "
    "dash DataValues.",
    "E is no_damage rather than out_of_scope and emits an explicit zero-damage state "
    "row.",
]
MODULE_COVERAGE = coverage(no_damage="E")
