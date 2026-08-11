"""Nidalee — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: W Bushwhack (human-form trap) prices 4 sourced 1s ticks
(this module's packet timing declaration); the Pounce variant is untouched.

E4 summon: W Bushwhack is a summoned trap.  The E2 pricing already
models one sprung trap's full 4-second DoT; ``w_traps`` (default 1,
capped at 10 — the level-18 trap cap "4 / 6 / 8 / 10 (based on level)")
prices additional pre-placed traps detonating during the fight, each as
its own full DoT: unlike Teemo's shrooms, Bushwhack traps have no
refresh note in the source, so every sprung trap deals its own damage.

Boundary: the E4 worklist note says "armor shred", but the current
patch has none — the cached leveling rows carry only the DoT
("Magic Damage Per Tick" / "Total Magic Damage"), and the live game
files (Community Dragon ``BushwhackAbility``) contain only the
``DamagePerSecond`` calculation.  Nothing is invented; the trap's
outgoing damage is the DoT above, and the armor-shred note is recorded
as stale in this module.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module

# "Up to a maximum of 4 / 6 / 8 / 10 (based on level) traps may be
# active at once" — 10 at level 18 (the test level).
_W_TRAP_CAP = 10


def _bushwhack_traps(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Bushwhack variant prices ``w_traps`` detonations; Pounce passthrough."""
    if int(ctx.options.get("w_variant", 0)) != 0:
        return _W_SLOT(ctx)
    entry = _W_SLOT(ctx)
    if entry is None:
        return None
    traps = min(max(int(ctx.options.get("w_traps", 1)), 1), _W_TRAP_CAP)
    if traps > 1:
        entry["parts"] = tuple(
            dataclasses.replace(part, count=part.count * traps)
            for part in entry["parts"]
        )
        entry["total_raw"] = entry.get("total_raw", 0.0) * traps
    inherited = entry.get("detail", "")
    entry["detail"] = (
        f"{traps} sprung Bushwhack trap(s), each dealing its own full "
        "4-tick DoT." + (f" {inherited}" if inherited else "")
    )
    return entry


PACKET_SHA256 = "96b6e873251ff23f700da4de3600cae2000d53929d77f7f315a48a227ac81d3d"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nidalee",
    PACKET_SHA256,
    packet_tick_fixes={
        "Bushwhack": {
            "count": 4,
            "first_tick": 1.0,
            "tick_interval": 1.0,
            "dot_duration": 4.0,
        }
    },
)
PACKET_SPEC = SLOTS.packet_spec
# The packet builder consumes these two explicit form selectors at parse time.
VARIANT_OPTION_KEYS = ("q_variant", "w_variant")
_W_SLOT = SLOTS["W"]
SLOTS["W"] = _bushwhack_traps
parse_abilities = build_parser(SLOTS, "Nidalee")
ASSUMPTIONS.extend(
    [
        "W (Bushwhack) is a summoned trap: one sprung trap prices the "
        "full 4-second DoT (E2-3 ticks); w_traps prices additional "
        "pre-placed traps, each with its own full DoT (the source has no "
        "refresh rule).",
        "The E4 worklist 'armor shred' note is stale for the current "
        "patch: the cached leveling rows and live game files carry only "
        "the trap DoT, so no shred is modeled.",
        "Trap placement, arm time, trigger radius and the trap's 6-HP "
        "health bar are state outside the damage model.",
    ]
)
OPTIONS.append(
    {
        "key": "w_traps",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": _W_TRAP_CAP,
        "label": "Sprung Bushwhack traps",
    }
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Nidalee self-healing events from its authored packet."""
    healing = []
    e = _healing._ability(champion_data, "E")
    e_rank = _healing._rank(ability_damages, "E")
    min_heal = _healing.extract_named(e, "Minimum Heal", e_rank, champion_stats)
    max_heal = _healing.extract_named(e, "Maximum Heal", e_rank, champion_stats)
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "E"
    ):
        healing.append(
            {
                "time": float(event.get("time", 0.0)),
                "amount": 0.0,
                "amount_formula": _healing._missing_health_scaled_heal(
                    min_heal, max_heal
                ),
                "source": "Primal Surge",
                "kind": "champion_ability",
                **_healing._trigger_fields(event),
            }
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Nidalee", derive_self_healing)
