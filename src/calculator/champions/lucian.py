"""Lucian — CP10.4 packet module with the E9-1 gap fixes.

E9-1 closes the two remaining audit gaps over the CP10.4 packet:
- R (The Culling) prices the FULL 3-second channel: 22 shots of the
  "Physical Damage Per Shot" packet (this module's packet timing declaration)
  at the sourced ~3s cadence instead of ONE shot.  The wiki cache
  carries only the per-shot row and the prose shot count ("up to 22
  shots ... over the duration"), so per-shot x 22 is the sourced
  full-channel value.  The wiki's crit-chance-scaled extra shots are
  zero at 0% crit and not modeled for crit builds.
- P (Lightslinger) is modeled as the engine's double-shot pattern:
  after casting an ability, the next basic attack within 3.5 seconds
  fires a second shot at 50% / 55% / 60% (based on level) AD physical
  damage (levels 1-6 / 7-12 / 13-18 — the wiki Template:Data band
  breakpoints).  The fight model prices one second shot per basic
  attack the rotation fires: in the standard weave every auto follows
  an ability cast, so per-auto second shots ARE the sourced per-cast
  mechanic.  The second shot applies on-hit effects and can crit,
  exactly the engine's double_shot path.

Q/W packets are correct single-instance reads.

Roadmap session 4 batch C (2026-08-21): E (Relentless Pursuit) is
reclassified from out_of_scope to no_damage. The pinned packet spec
already carried E as ``kind: "no_damage"`` and the compiler's
``_no_formula_parser`` was already emitting a proper, user-visible
zero-damage row at runtime -- MODULE_COVERAGE was the only place still
reading "out_of_scope" for a slot that was never silently absent. The
cached ability JSON's three effect entries (cooldown refund on
Lightslinger hit, the dash itself, the attack-timer reset / free-cast
window) all carry empty ``leveling`` arrays. Corroborated by the game
binary (``data/bin/characters/lucian.bin.json``,
``Characters/Lucian/Spells/LucianEAbility/LucianE``): ``mSpell`` has no
``mSpellCalculations`` table, and its ``DataValues`` are all
non-damage parameters (``CDRefundBase`` 1.0s, ``CDRefundChampion`` 2.0s,
``MaxDistance``/``MinDistance`` 425/200, ``DashSpeed`` 1350) -- no
damage node exists for E to price. E now rides an explicit,
champion-authored no-damage row via ``module_helpers.no_damage``
(Kalista P/R, Jayce P precedent) instead of the compiler's generic
fallback text.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
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


def _lightslinger_ratio(level: int) -> float:
    """The second shot's AD ratio at a champion level."""
    for min_level, ratio in _LIGHTSLINGER_RATIO_BANDS:
        if level >= min_level:
            return ratio
    return _LIGHTSLINGER_RATIO_BANDS[-1][1]


def _lightslinger(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: second shot after each ability — the engine double-shot path."""
    passive = ctx.ability("P")
    if passive is None:
        return None
    return {
        "name": "Lightslinger",
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "double_shot": {
            "name": "Lightslinger",
            "ad_ratio": _lightslinger_ratio(ctx.level),
        },
    }


def _relentless_pursuit(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the cooldown-refunding dash — documented zero-damage row.

    All three cached effect rows carry empty leveling (cooldown refund
    on Lightslinger hit, the dash, the attack-timer reset); the game
    binary's ``LucianE`` spell record carries no ``mSpellCalculations``
    table, only non-damage DataValues (cooldown-refund seconds, dash
    range/speed). E prices nothing.
    """
    return no_damage(
        ctx,
        name="Relentless Pursuit",
        reason=(
            "Active: Lucian dashes in the target direction, resetting his "
            "basic attack timer. Passive: Relentless Pursuit's current "
            "cooldown is reduced by 1s per Lightslinger shot hit (2s "
            "against champions). Pure movement/cooldown-refund state -- "
            "no leveling row and no combat-damage interaction; "
            "corroborated by the game binary's LucianE spell record, "
            "which carries no mSpellCalculations table."
        ),
    )


PACKET_SHA256 = "3fe0c536a453a203c13c7bb713274cbc217785ea29e4723c090c474b7607b9e6"

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
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["P"] = _lightslinger
SLOTS["E"] = _relentless_pursuit
parse_abilities = build_parser(SLOTS, "Lucian")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (The Culling) prices all 22 sourced shots of the 3-second "
    "channel (per-shot x 22; the wiki cache carries only the per-shot "
    "row and the prose shot count, not a Total row).  The "
    "crit-chance-scaled extra shots of the wiki's '+ 0 : 6 (based on "
    "critical strike chance)' template are zero at 0% crit and not "
    "modeled for crit builds.",
    "P (Lightslinger) fires a second shot on the next basic attack "
    "after each ability cast at 50% / 55% / 60% (based on level) AD "
    "(levels 1-6 / 7-12 / 13-18, wiki Template:Data bands).  The fight "
    "model prices one second shot per basic attack the rotation fires "
    "(the standard weave attacks after every ability cast); the second "
    "shot applies on-hit effects and can crit (engine double_shot "
    "path).",
    "E (Relentless Pursuit) carries no sourced damage row: all three "
    "cached effect entries (cooldown refund on Lightslinger hit, the "
    "dash, the attack-timer reset) have empty leveling, and the game "
    "binary's LucianE spell record has no mSpellCalculations table -- "
    "only non-damage DataValues (cooldown-refund seconds, dash "
    "range/speed). E is no_damage, not out_of_scope, and emits an "
    "explicit zero-damage state row rather than staying silently "
    "absent.",
]
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "no_damage",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"
