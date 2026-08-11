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
"""

from __future__ import annotations

from typing import Any

from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .source_receipts import load_champion_sources

PACKET_SHA256 = "26e75628def53875687d8141eb419c4f2d3a2adb6e68ee714cd39cb4e446ad4e"

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module(
        "Samira",
        PACKET_SHA256,
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
    )
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec
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
    return min(max(int(ctx.options.get("p_style_stacks", 0)), 0), _STYLE_MAX)


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
            "maximum stacks); the melee blade-zone bonus magic damage is "
            "state."
        ),
    )


def _inferno_trigger(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: reviewed packet pricing + the S-rank requirement note."""
    entry = _BATCH_SLOTS["R"](ctx)
    if entry is not None and _style_stacks(ctx) >= _STYLE_MAX:
        entry["detail"] = (
            f"{entry.get('detail', '')} Requires S rank ({_STYLE_MAX} "
            "Style stacks); Style stacks are consumed at the end of the "
            "effect."
        )
    return entry


SLOTS = {
    "P": _daredevil_impulse,
    "Q": _BATCH_SLOTS["Q"],
    "W": _BATCH_SLOTS["W"],
    "E": _BATCH_SLOTS["E"],
    "R": _inferno_trigger,
}
parse_abilities = build_parser(SLOTS, "Samira")

OPTIONS = [
    {
        "key": "p_style_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 6,
        "label": "Style stacks (6 = S rank, R ready)",
    },
    {
        "key": "w_active",
        "type": "bool",
        "default": False,
        "label": "W (Blade Whirl) active against selected skillshots",
    },
    {
        "key": "w_active_from",
        "type": "float",
        "default": 0.0,
        "min": 0.0,
        "max": 120.0,
        "label": "W active start time in seconds",
    },
    {
        "key": "w_active_seconds",
        "type": "float",
        "default": 0.0,
        "min": 0.0,
        "max": 0.75,
        "label": "W active seconds; zero uses the sourced 0.75 second duration",
    },
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

ASSUMPTIONS = [
    "Style caps at 6 stacks (6-second expiry and unique-hit generation "
    "not modeled); p_style_stacks is the explicit pre-stack state",
    "At 6 stacks (S rank) Inferno Trigger is available and consumes all "
    "stacks at the end of the effect",
    "Style's bonus movement speed (2.75/3/3.25/3.5% per stack by level) "
    "is state, not damage",
    "Q/W/E and R damage keep the reviewed CP10.7 packet pricing (R: 10 "
    "sourced 0.2s shots)",
    "W Blade Whirl destroys selected champion projectiles during its sourced "
    "0.75 second window; the source selection is an explicit incoming-event "
    "contract.",
]

SOURCES = load_champion_sources("Samira")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
