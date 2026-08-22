"""Samira — Style (6-stack) S-rank unlock system.

Stack mechanics modeled (E3):
- P (Daredevil Impulse): damaging basic attacks and abilities against
  unique champions build Style (cap 6). Each stack grants 2.75 / 3 /
  3.25 / 3.5% (levels 1 / 6 / 11 / 16) bonus movement speed, up to
  16.5 / 18 / 19.5 / 21% at 6 stacks.  At maximum stacks (S rank),
  Samira can cast Inferno Trigger; Style stacks are consumed at the end
  of the effect.  ``p_style_stacks`` is the explicit pre-stack state.
- R (Inferno Trigger) keeps the reviewed CP10.7 packet pricing (10
  sourced 0.2s shots, E2 fix); its detail notes the S-rank requirement
  when Style is maxed.

Q (Flair), W (Blade Whirl) and E (Wild Rush) keep the reviewed CP10.7
packet pricing. All numeric values are read from the champion JSON data.

P is ``out_of_scope``, not ``no_damage``: Daredevil Impulse's second
innate does damage this module cannot price.  Blade attacks (basic
attacks inside 200 units), Blade Whirl, Wild Rush and Flair's slash and
explosives each deal 2 : 21 (based on level) (+ 3.5% : 11.32% (based on
level) AD) bonus magic damage, doubled at the target's full missing
health.  The engine has no range-gated per-hit rider that attaches to
ability parts as well as to the basic-attack stream, and the packet's Q
row is one number for both the ranged shot and the melee slash, so the
rider has no slot to ride.  The other four slots price their own rows.
"""

from __future__ import annotations

from typing import Any

from .engine import SlotCtx
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .inputs import bool_option, float_option, int_option
from .module_contract import coverage

PACKET_SHA256 = "26e75628def53875687d8141eb419c4f2d3a2adb6e68ee714cd39cb4e446ad4e"

_STYLE_MAX = 6
# Style bonus movement speed per stack by level bracket (wiki prose:
# 2.75% / 3% / 3.25% / 3.5% at levels 1 / 6 / 11 / 16).
_STYLE_MS_BRACKETS = ((16, 3.5), (11, 3.25), (6, 3.0), (1, 2.75))


def _style_ms_per_stack(level: int) -> float:
    for min_level, percent in _STYLE_MS_BRACKETS:
        if level >= min_level:
            return percent
    return _STYLE_MS_BRACKETS[-1][1]


def _style_stacks(ctx: SlotCtx) -> int:
    return min(max(int(ctx.option("p_style_stacks")), 0), _STYLE_MAX)


def _daredevil_impulse(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Style stack state row (movement speed; R unlock at 6)."""
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = _style_stacks(ctx)
    per_stack = _style_ms_per_stack(ctx.level)
    if stacks >= _STYLE_MAX:
        state = (
            f"{stacks}/6 Style stacks (S rank): Inferno Trigger is "
            "available and consumes all stacks at the end of the effect"
        )
    else:
        state = (
            f"{stacks}/6 Style stacks; Inferno Trigger requires S rank "
            f"({_STYLE_MAX} stacks)"
        )
    return no_damage(
        ctx,
        name=ability.get("name", "Daredevil Impulse"),
        reason=(
            f"Style: {state}.  Each stack grants {per_stack:.2f}% bonus "
            f"movement speed (up to {per_stack * _STYLE_MAX:.1f}% at "
            "maximum stacks); the blade-zone bonus magic damage is not "
            "priced (out_of_scope — see the module docstring)."
        ),
    )


def _inferno_trigger(packet_r):
    """R: reviewed packet pricing + the S-rank requirement note."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_r(ctx)
        if entry is not None and _style_stacks(ctx) >= _STYLE_MAX:
            entry["detail"] = (
                f"{entry.get('detail', '')} Requires S rank ({_STYLE_MAX} "
                "Style stacks); Style stacks are consumed at the end of the "
                "effect."
            )
        return entry

    return parse


# Cached kit review: reviewed cc-free on every damaging cast.  Flair's shot
# and slash, Blade Whirl's two slashes, Wild Rush's dash and Inferno
# Trigger's torrent all only deal damage; the projectile destruction on W
# and the takedown reset on E are not control applied to a target.  P is
# absent: Daredevil Impulse is a state row with no damage of its own, and
# its knock-up rider fires only on the empowered basic attack against a
# target that is already a monster or airborne — an auto-stream effect, not
# an ability event.
MODULE_CC = {"Q": "none", "W": "none", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Samira",
    PACKET_SHA256,
    assumption_overrides=(
        "Style caps at 6 stacks (6-second expiry and unique-hit generation not modeled); "
        "p_style_stacks is the explicit pre-stack state",
        "At 6 stacks (S rank) Inferno Trigger is available and consumes all stacks at the end of "
        "the effect",
        "Style's bonus movement speed (2.75/3/3.25/3.5% per stack by level) is state, not damage",
        "Daredevil Impulse's blade-zone rider (2 : 21 by level + 3.5% : 11.32% AD bonus magic "
        "damage on melee-range basic attacks, Blade Whirl, Wild Rush and Flair's slash, doubled "
        "at full missing health) is NOT priced — P is out_of_scope",
        "Q/W/E and R damage keep the reviewed CP10.7 packet pricing (R: 10 sourced 0.2s shots)",
        "W Blade Whirl destroys selected champion projectiles during its sourced "
        "0.75 second window; the source selection is an explicit incoming-event "
        "contract.",
    ),
    packet_tick_fixes={
        "Blade Whirl": {
            "count": 2,
            "first_tick": 0.0,
            "tick_interval": 0.75,
        },
        "Inferno Trigger": {
            "count": 10,
            "first_tick": 0.0,
            "tick_interval": 0.2,
            "dot_duration": 2.013,
        },
    },
    # Flair's shot lands on "the first enemy hit" and Wild Rush damages
    # what its dash passes through once — the boundary claim that
    # carries MODULE_CC's reviewed answers into the event ledger.  W
    # and R already author their own slash and shot timings above.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "P": _daredevil_impulse,
    },
    slot_wrappers={
        "R": _inferno_trigger,
    },
    slot_order=("P", "Q", "W", "E", "R"),
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    int_option(
        "p_style_stacks",
        0,
        minimum=0,
        maximum=6,
        label="Style stacks (6 = S rank, R ready)",
    ),
    bool_option(
        "w_active", False, label="W (Blade Whirl) active against selected skillshots"
    ),
    float_option(
        "w_active_from",
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="W active start time in seconds",
    ),
    float_option(
        "w_active_seconds",
        0.0,
        minimum=0.0,
        maximum=0.75,
        label="W active seconds; zero uses the sourced 0.75 second duration",
    ),
    {
        "key": "w_blocked_skillshots",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Skillshot slots to destroy; an empty list destroys all marked skillshots"
        ),
    },
]


MODULE_COVERAGE = coverage(out_of_scope="P")
