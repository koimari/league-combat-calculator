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

Coverage: P (Prowl) grants movement speed in brush and marks a Hunted
target, and R (Aspect of the Cougar) is the form swap itself — movement
speed and transform, axes the engine does not have. Cougar form is still
reachable: the ``w_variant`` packet option selects the cougar abilities
directly, so R has no state of its own left to price.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .engine import SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module

# "Up to a maximum of 4 / 6 / 8 / 10 (based on level) traps may be
# active at once" — 10 at level 18 (the test level).
_W_TRAP_CAP = 10


def _bushwhack_traps(packet_w):
    """W: Bushwhack variant prices ``w_traps`` detonations; Pounce passthrough."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        if int(ctx.option("w_variant")) != 0:
            return packet_w(ctx)
        entry = packet_w(ctx)
        if entry is None:
            return None
        traps = min(max(int(ctx.option("w_traps")), 1), _W_TRAP_CAP)
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

    return parse


PACKET_SHA256 = "96b6e873251ff23f700da4de3600cae2000d53929d77f7f315a48a227ac81d3d"

# The packet builder consumes these two explicit form selectors at parse time.

# Cached kit review: reviewed cc-free, whole kit.  No entry applies any
# crowd control to an enemy — Javelin Toss and Takedown only deal magic
# damage, Bushwhack's trap "deal[s] magic damage every second over 4
# seconds" (the old slow is gone from the cached text), Pounce and Swipe
# damage on arrival, Primal Surge heals, and Prowl / Aspect of the Cougar
# are Nidalee's own movement and form swap.  Every damaging slot says so
# explicitly, which is what lets control-armed item passives price a
# Nidalee fight instead of withholding on an unreviewed kit.
MODULE_CC = {"Q": "none", "W": "none", "E": "none"}

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
    # Javelin Toss and Takedown each land one hit, Swipe slashes once, and
    # W's Pounce variant damages once on arrival — the boundary claim that
    # carries MODULE_CC's reviewed answers into the event ledger.  W's
    # Bushwhack variant authors its own four-tick timing above and keeps it.
    single_hit_slots=frozenset({"Q", "W", "E"}),
    slot_wrappers={
        "W": _bushwhack_traps,
    },
    cc_kinds=MODULE_CC,
)
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

SELF_HEALING_RULE = declare_healing_rule("Nidalee")
