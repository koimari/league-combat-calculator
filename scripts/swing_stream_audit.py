"""The swing-stream gate: a per-attack rider or an attack-speed row rides the swings.

A cached slot whose text says its damage lands on every basic attack, or
whose leveling carries a Bonus Attack Speed row, must publish an entry the
fight engine prices on the swing stream (an ``on_hit``, an
``auto_attack_override`` window, a ``stacking_dot``, a swing rider ratio, or
a ``stat_buff`` with attack speed); otherwise the packet compiler prices
the row once per cast (a Stacked Deck read as one hit per fight, a Lightning
Rush whose +80% is never read).  Every slot the scan flags that publishes
none of them is on the pinned ``FRONTIER`` with its reason, and
``tests/test_swing_stream_audit.py`` holds the scan to that list.

Usage::

    python scripts/swing_stream_audit.py          # exit 1 on any drift
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.champions import (
    parse_champion_abilities,
    registered_champion_names,
)
from src.calculator.champions.stat_grants import ATTACK_SPEED_ROW
from src.calculator.data_fetcher import get_champion
from src.calculator.fight.cast_slots import _base_slot
from src.calculator.stats import calculate_total_stats

LEVEL = 18
FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
SLOTS = ("P", "Q", "W", "E", "R")
#: The issue's probe: a 10-second timed fight with the autos on, which is
#: the window the pipeline injects (a timed-only row such as Kai'Sa E's
#: Supercharge average emits nothing without one).
TIMED_FIGHT = {"fight_duration_seconds": 10.0, "auto_attack_uptime": 1.0}

#: The cached phrasings of "damage on every basic attack".  "applies on-hit
#: effects" is the spellblade matrix's shape (an ability that carries the
#: build's on-hits), and "next basic attack(s)" is one empowered swing per
#: cast (Nasus Q, Udyr's stances); neither is a stream, so a sentence
#: saying either is not a rider.
PER_ATTACK_TEXT = re.compile(
    r"basic attacks (?:are empowered to )?(?:deal|also deal)"
    r"|damage on-hit(?! effects)"
    r"|(?:each|every) basic attack[^.]{0,80}damage",
    re.IGNORECASE,
)
NEXT_ATTACK_TEXT = re.compile(
    r"next (?:\d+ |two |three )?(?:basic |empowered )?attacks?", re.IGNORECASE
)

#: Entry keys the fight engine prices per swing.
SWING_KEYS = frozenset(
    {
        "on_hit",
        "auto_attack_override",
        "stacking_dot",
        "double_shot",
        "auto_attack_conversion",
        "basic_attack_true_ratio",
        "critical_strike_magic_ratio",
        "empowers_next_auto",
        # A kit ramp re-rates every swing the walker lands, which is the same
        # per-swing pricing a flat bonus_attack_speed stat_buff gets below.
        "swing_ramp",
    }
)

#: ``(champion, slot)`` the scan flags whose module states the boundary
#: instead of publishing a swing key.  Each reason names why the row is
#: priced as it is; removing a fixed slot from here is part of fixing it.
FRONTIER: dict[tuple[str, str], str] = {
    ("Ashe", "P"): (
        "Frost Shot's crit-as-bonus rides the Q row's auto_attack_override while "
        "Ranger's Focus is active (the default); the P row carries it only when Q is off."
    ),
    ("Ekko", "W"): (
        "Parallel Convergence's passive on-hit needs the target below 30% health, the "
        "w_passive_ready option (default off)."
    ),
    ("Elise", "P"): (
        "Spider Queen's on-hit is spider form, the spider_form option (default off: "
        "human form)."
    ),
    ("Elise", "W"): (
        "The W row is the human Volatile Spiderling; Skittering Frenzy's spider-form "
        "attack speed is not priced in either form (the spider stream is out of scope)."
    ),
    ("K'Sante", "R"): (
        "All Out's attack speed rides the all_out option (default off): the state also "
        "cuts his resistances, so it is the user's call."
    ),
    (
        "Sion",
        "P",
    ): "Glory in Death's on-hit is the post-death state, never a live fight.",
    ("Twitch", "Q"): (
        "Element of Surprise needs an Ambush to break, the q_ambush_break option "
        "(default off); with it on the Q row places the window."
    ),
    ("Vi", "W"): (
        "Denting Blows' third-hit attack speed rides the stack cadence the module "
        "documents as a gap; the shred is priced, the steroid is not."
    ),
    ("Yuumi", "Q"): (
        "Prowling Projectile's on-hit is her Best Friend's (an ally grant), not "
        "Yuumi's own swing."
    ),
}


def _slot_text(ability: Mapping[str, Any]) -> str:
    return " ".join(
        str(effect.get("description", "")) for effect in ability.get("effects", ())
    )


def _has_attack_speed_row(ability: Mapping[str, Any]) -> bool:
    return any(
        row.get("attribute") == ATTACK_SPEED_ROW
        for effect in ability.get("effects", ())
        for row in effect.get("leveling", ())
    )


def _per_attack_rider(text: str) -> bool:
    """Whether a sentence of the slot's text puts damage on every basic attack."""
    return any(
        PER_ATTACK_TEXT.search(sentence) and not NEXT_ATTACK_TEXT.search(sentence)
        for sentence in re.split(r"(?<=[.!])\s+", text)
    )


def _entries_for(results: Mapping[str, Mapping[str, Any]], slot: str) -> list:
    """Every published row the slot owns: its own key and its ``<slot>_*`` rows."""
    own = "passive" if slot == "P" else slot
    return [
        entry
        for key, entry in results.items()
        if key == own or _base_slot(key) in (own, slot)
    ]


def _rides_the_swings(entries: list, *, attack_speed: bool) -> bool:
    for entry in entries:
        if SWING_KEYS & set(entry):
            return True
        if attack_speed and "bonus_attack_speed" in (entry.get("stat_buff") or {}):
            return True
    return False


def scan(names: list[str] | None = None) -> dict[tuple[str, str], str]:
    """``(champion, slot) -> what the cache says`` for every slot that rides no swing key."""
    hits: dict[tuple[str, str], str] = {}
    for name in names or registered_champion_names():
        data = get_champion(name)
        stats = calculate_total_stats(data, LEVEL, [])
        results = parse_champion_abilities(
            data,
            LEVEL,
            stats.get("ability_power", 0.0),
            FULL_RANKS,
            champion_stats=stats,
            champion_options=dict(TIMED_FIGHT),
        )
        for slot in SLOTS:
            abilities = data.get("abilities", {}).get(slot) or ()
            text = " ".join(_slot_text(ability) for ability in abilities)
            attack_speed = any(_has_attack_speed_row(ability) for ability in abilities)
            rider = _per_attack_rider(text)
            if not (attack_speed or rider):
                continue
            if _rides_the_swings(
                _entries_for(results, slot), attack_speed=attack_speed
            ):
                continue
            hits[(name, slot)] = (
                "attack-speed row" if attack_speed else "per-attack rider text"
            )
    return hits


def drift() -> tuple[dict[tuple[str, str], str], list[tuple[str, str]]]:
    """Slots the scan flags off the frontier, and frontier rows the scan does not flag."""
    hits = scan()
    new = {key: why for key, why in hits.items() if key not in FRONTIER}
    stale = [key for key in FRONTIER if key not in hits]
    return new, stale


def main() -> int:
    new, stale = drift()
    for (champion, slot), why in sorted(new.items()):
        print(f"UNPRICED {champion} {slot}: {why}, no swing key published")
    for champion, slot in sorted(stale):
        print(f"STALE frontier row {champion} {slot}: the slot now rides the swings")
    if new or stale:
        return 1
    print(
        f"OK: {len(FRONTIER)} frontier rows, every other flagged slot rides the swings"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
