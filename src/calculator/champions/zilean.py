"""Zilean — CP10.10 full-entry-reviewed packet module.

Only Q deals damage.  R is priced as the Chronoshift revive below, so it
is ``modeled`` through that channel rather than through its own row.  The
other three slots carry no sourced damage/heal/shield number at all, so
they are ``no_damage`` rather than unmodelled mechanics:

  - P (Time in a Bottle) has empty cached leveling — it grants Zilean and
    a selected ally experience only.
  - W (Rewind) has empty cached leveling; it "reduces the remaining
    cooldowns of Time Bomb and Time Warp by 10 seconds each", and the
    fight engine's rotation is a static per-fight cast count, so a
    mid-fight cooldown refund changes nothing it prices.  What it *does*
    change is reachable through the ``q_second_bomb`` state below: a
    Q -> W -> Q sequence is how the second bomb lands inside the first
    one's fuse.
  - E (Time Warp) carries only a "Movement Speed Modifier" row
    (40/55/70/85/99%, a slow on an enemy or a haste on an ally), and
    ``ability_spec.ACTION_BLOCKING_CC_KINDS`` deliberately excludes
    "slow", so a pure movement-speed change creates no action downtime
    either.
"""

from dataclasses import replace

from .inputs import champion_stat
from .packet_module import build_packet_module

from ..champions.skill_orders import get_ability_rank
from .slotlib import with_control

PACKET_SHA256 = "9b4c1e8f16ad0424b82b068c7d55f47892f0345ff70020773135903cc8233776"

# Time Bomb's damage is the detonation's, not the throw's: "After 3
# seconds, or when the attached unit dies, the bomb explodes to deal magic
# damage to nearby enemies" (cached Q prose).
_Q_FUSE_SECONDS = 3.0


def _time_bomb(compiled):
    """Q: a lone bomb waits out its fuse; a second bomb detonates it now.

    One cast, two sourced answers, so they are authored per part rather
    than in ``MODULE_CC`` (the Alistar E / Xayah E precedent): a lone Time
    Bomb only "explodes to deal magic damage", while "the bomb detonates
    immediately if another bomb attaches itself to the same unit, stunning
    nearby enemies".  Reaching the second bomb inside the fuse needs W
    (Rewind) to refund Q's cooldown, which the static rotation cannot
    derive — so it is the player-declared ``q_second_bomb`` state, and it
    moves the detonation to the cast boundary as well as arming the
    sourced Stun Duration row.

    That stun rides the detonation itself — one hit, one instant, one
    control — so ``with_control`` puts the sourced interval and the atoms
    it was read from on that part rather than beside it as a separate
    control event.  The row lives on the third cached effect
    (``Zilean.Q[0].effects[2].leveling[0]``, "Stun Duration"
    1.1 : 1.5), which is why the branch names ``effect_index=2``.
    """

    def parse(ctx):
        entry = compiled(ctx)
        if entry is None:
            return None
        second_bomb = bool(ctx.option("q_second_bomb"))
        entry["parts"] = tuple(
            replace(part, time_offset=0.0 if second_bomb else _Q_FUSE_SECONDS)
            for part in entry.get("parts") or ()
        )
        if second_bomb:
            entry = with_control(
                lambda _ctx, built=entry: built,
                kind="stun",
                duration_attr="Stun Duration",
                effect_index=2,
            )(ctx)
        else:
            entry["parts"] = tuple(
                replace(part, cc_kind="none") for part in entry["parts"]
            )
        entry["cc_reviewed"] = True
        return entry

    return parse


# Q is authored per part by ``_time_bomb`` (its kind depends on the
# second-bomb state), and P/W/E/R price no damage, so the module declares
# no per-slot kind of its own.
MODULE_CC: dict[str, str] = {}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zilean",
    PACKET_SHA256,
    slot_wrappers={"Q": _time_bomb},
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "q_second_bomb",
        "type": "bool",
        "default": False,
        "label": "Q second bomb attached to the target",
        "rotation": {
            "role": "self_state",
            "slot": "Q",
            "note": (
                "A second Time Bomb detonates the first immediately and "
                "stuns; W (Rewind) is what refunds Q's cooldown in time, "
                "and no cast order the engine walks can derive it."
            ),
        },
    },
]

# E8d: sourced Chronoshift revive values.  Cached R leveling (data/
# champions.json, Zilean R Chronoshift) Heal row: 600 / 850 / 1100 (+ 200% AP)
# by R rank; prose: "If the target takes fatal damage within the duration,
# they enter resurrection for 3 seconds ... Afterwards, they revive while
# being healed."  Cooldown is 120 / 90 / 60 by rank.  The engine's revive
# state transition consumes ``StartingDefenses.revive_*`` fields; the shared
# defense resolver wires these per champion.
REVIVE_DELAY_SECONDS = 3.0
_REVIVE_HEAL_BASE = (600.0, 850.0, 1100.0)
_REVIVE_HEAL_AP_RATIO = 2.0  # "+ 200% AP"
_REVIVE_COOLDOWN = (120.0, 90.0, 60.0)


def starting_revive_defense(level: int, stats: dict[str, float]) -> dict[str, float]:
    """Return Zilean's sourced Chronoshift revive fields for StartingDefenses."""
    rank = max(1, min(3, get_ability_rank("R", level, "Zilean")))
    amount = _REVIVE_HEAL_BASE[rank - 1] + _REVIVE_HEAL_AP_RATIO * float(
        champion_stat(stats, "ability_power")
    )
    return {
        "revive_health_amount": amount,
        "revive_delay": REVIVE_DELAY_SECONDS,
        "revive_cooldown": _REVIVE_COOLDOWN[rank - 1],
    }


# R's own packet row prices nothing; the revive above is what the engine
# prices for the slot (1100.0 at rank 3 with no AP).
MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "no_damage",
    "E": "no_damage",
    "R": "modeled",
}
COVERAGE_CHANNELS = {"R": ("starting_revive_defense",)}
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q's stun is emitted only when the explicit second-bomb state is selected; "
    "the second bomb detonates the first bomb immediately (so the detonation "
    "moves from its 3s fuse to the cast boundary) and uses the sourced "
    "Stun Duration row",
    "R (Chronoshift) is modeled as the sourced revive state: 600 / 850 / 1100 "
    "(+ 200% AP) restored after a 3s resurrection on a 120 / 90 / 60s cooldown "
    "by rank (cached R Heal row).",
    "P (Time in a Bottle), W (Rewind), and E (Time Warp) carry no sourced "
    "damage/heal/shield row (P and W leveling are empty; E's only leveling "
    "row is a Movement Speed Modifier, and slow/haste effects create no "
    "action downtime in this engine) — all three are no_damage, not "
    "out_of_scope.",
]
