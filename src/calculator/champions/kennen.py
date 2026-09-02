"""Kennen — full-entry reviewed CP10.3 module.

P (Mark of the Storm) is a per-target stack walk: every ability hit and
every four-stack Electrical Surge attack applies one mark, and the third
mark against a target consumes them all as a stun.  The slot walks the
fight's own hit stream through that cycle rather than marking one cast.

Option keys consumed by the shared parser: "w_empowered", "r_bolts",
"mark_stacks".
"""

import math
import re
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_contract import coverage
from .module_helpers import (
    REVIEWED_MODULE_ASSUMPTIONS,
    ability_cast_times,
    no_damage,
)
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    effect_description,
    extract_cooldown,
    extract_description_control_durations,
    extract_description_duration,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources

# Mark of the Storm is prose only — its cached effects carry no leveling
# row — so the cap, the repeat-stun rule and Slicing Maelstrom's own stack
# limit are read from the sentences that state them and raise when a patch
# stops stating them.  The mark window (6s) and the full stun (1.25s) come
# from the typed prose readers.
_STACK_CAP_RE = re.compile(r"stacking up to (\d+) times")
_REPEAT_STUN_RE = re.compile(
    r"stun duration is reduced to ([\d.]+) seconds? if this occurs on the "
    r"same target again within ([\d.]+) seconds"
)
_STORM_STACK_CAP_RE = re.compile(
    r"Slicing Maelstrom can apply only up to (\d+) stacks on a target"
)
_MARK_EFFECT = 0
_STUN_EFFECT = 1
_STORM_EFFECT = 2
#: Bolt cadence Slicing Maelstrom's own row authors (cast + 0.5s, every 0.5s).
_BOLT_OFFSET = 0.5
_BOLT_INTERVAL = 0.5


def _electrical_surge(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    active = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    passive = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    result = ability_on_hit_entry(
        ability_name(ability),
        rank,
        "magic",
        {
            "name": "Electrical Surge passive",
            "damage_per_hit": (passive if bool(ctx.option("w_empowered")) else 0.0),
            "damage_type": "magic",
        },
        extract_cooldown(ability, rank),
    )
    result["parts"] = (DamagePart("magic", active),)
    result["total_raw"] = active
    result["detail"] = (
        "Active surge plus an explicit four-stack empowered on-hit branch."
    )
    return result


def _slicing_maelstrom(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    bolts = max(1, min(6, int(ctx.option("r_bolts"))))
    per = extract_named(ability, "Magic Damage Per Bolt", rank, ctx.stats, ctx.target)
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per * bolts,
        "parts": (
            DamagePart("magic", per, count=bolts, time_offset=0.5, hit_interval=0.5),
        ),
        "detail": (
            f"{bolts} ordered bolts; later strikes use the sourced escalating "
            "storm packet."
        ),
    }


def _sourced(pattern: re.Pattern[str], text: str, what: str) -> re.Match[str]:
    """One cached sentence's numbers, or a refusal naming what went missing."""
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"Kennen P: the cached kit no longer states {what}")
    return match


def _mark_stream(ctx: SlotCtx, duration: float, storm_cap: int) -> list[float]:
    """Every Mark of the Storm application on this target, in time order.

    "Kennen's abilities apply a stack of Mark of the Storm to enemies hit",
    so each Q/W/E cast applies one at its cast time and Slicing Maelstrom
    applies one per bolt on its own authored cadence, capped by the cached
    "can apply only up to N stacks on a target".  The four-stack Electrical
    Surge attack "appl[ies] a stack of Mark of the Storm on-hit" too: with
    the passive opening at maximum stacks it lands on the first swing and
    on every ``cap + 1``-th after it.
    """
    times: list[float] = []
    for time, slot in ability_cast_times(ctx, duration, ("Q", "W", "E", "R")):
        if slot != "R":
            times.append(time)
            continue
        bolts = min(max(1, min(6, int(ctx.option("r_bolts")))), storm_cap)
        times.extend(
            time + _BOLT_OFFSET + _BOLT_INTERVAL * index for index in range(bolts)
        )
    rate = ctx.stat("attack_speed") * float(ctx.option("auto_attack_uptime"))
    if rate > 0 and bool(ctx.option("w_empowered")):
        period = _surge_stack_cap(ctx) + 1
        times.extend(
            index / rate
            for index in range(math.floor(rate * duration))
            if index % period == 0
        )
    return sorted(time for time in times if time <= duration)


def _surge_stack_cap(ctx: SlotCtx) -> int:
    """Electrical Surge's own attack-stack cap, from its cached sentence."""
    ability = ctx.ability("W")
    if ability is None:
        raise ValueError("Kennen P: the cached kit has no Electrical Surge entry")
    return int(
        _sourced(
            _STACK_CAP_RE,
            effect_description(ability, 0),
            "Electrical Surge's 'stacking up to N times'",
        ).group(1)
    )


def _mark_of_the_storm(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: walk this target's mark applications through stack -> stun cycles.

    Each application refreshes the sourced mark window; the third consumes
    them all and stuns.  ``mark_stacks`` is the opening count — the one
    thing no walk can derive, because a third mark would already have been
    spent, which is why it stops at the cap minus one.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    cap = int(
        _sourced(
            _STACK_CAP_RE,
            effect_description(ability, _MARK_EFFECT),
            "Mark of the Storm's 'stacking up to N times'",
        ).group(1)
    )
    window = extract_description_duration(ability, _MARK_EFFECT)
    durations = extract_description_control_durations(ability, _STUN_EFFECT)
    if window is None or not durations:
        raise ValueError(
            "Kennen P: the cached innate no longer states the mark window or "
            "the stun it ends in"
        )
    repeat = _sourced(
        _REPEAT_STUN_RE,
        effect_description(ability, _STUN_EFFECT),
        "the repeat stun's reduced duration and its window",
    )
    storm_cap = int(
        _sourced(
            _STORM_STACK_CAP_RE,
            effect_description(ability, _STORM_EFFECT),
            "Slicing Maelstrom's own per-target stack limit",
        ).group(1)
    )

    stacks = min(max(int(ctx.option("mark_stacks")), 0), cap - 1)
    fight = ctx.options.get("fight_duration_seconds")
    stuns: list[tuple[float, float]] = []
    last_application: float | None = 0.0 if stacks else None
    if fight is not None:
        for time in _mark_stream(ctx, float(fight), storm_cap):
            if last_application is not None and time - last_application > window:
                stacks = 0
            stacks += 1
            last_application = time
            if stacks >= cap:
                previous = stuns[-1][0] if stuns else None
                shortened = previous is not None and time - previous < float(
                    repeat.group(2)
                )
                stuns.append(
                    (time, float(repeat.group(1)) if shortened else durations[0])
                )
                stacks = 0
                last_application = None
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"{len(stuns)} third-mark stun(s) "
            + (
                "at " + ", ".join(f"{time:.2f}s/{length:g}s" for time, length in stuns)
                if stuns
                else f"(the walk ends at {stacks}/{cap} marks)"
            )
            + f"; marks last {window:g}s, refreshing on each application, and "
            "the stun's energy refund stays ordered control state"
        ),
    )


SLOTS = {
    "P": _mark_of_the_storm,
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _electrical_surge,
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": _slicing_maelstrom,
}
OPTIONS = [
    bool_option("w_empowered", True, label="Four-stack Electrical Surge attack"),
    int_option("r_bolts", 6, minimum=1, maximum=6, label="Slicing Maelstrom bolts"),
    int_option(
        "mark_stacks",
        0,
        minimum=0,
        maximum=2,
        label="Marks of the Storm already on the target (a third would "
        "already have stunned)",
    ),
]
ASSUMPTIONS = [
    *list(REVIEWED_MODULE_ASSUMPTIONS),
    "The Mark of the Storm walk merges the fight's ability casts at the "
    "Braum-pattern schedule (each learned slot at t=0 and every hasted "
    "cooldown after) with Slicing Maelstrom's own bolt cadence and, when "
    "w_empowered is set, the Electrical Surge attack on the first swing "
    "and every fifth after it; one set of hands and item cooldown refunds "
    "are not mirrored",
    "Mark applications are counted against ONE target — the pair fight's "
    "own — so allied hits and multi-target spread are outside the walk",
]
SOURCES = load_champion_sources("Kennen")

# MODULE_CC is empty, and the Mark of the Storm walk is why rather than an
# excuse for it.  The stun sits on the target's stack count, not on any
# ability — "Kennen's abilities apply a stack of Mark of the Storm to
# enemies hit ... stacking up to 3 times" and "the third stack against a
# target consumes them all to stun them for 1.25 seconds".  Which casts of
# a slot are the third application is therefore a property of the fight's
# hit stream, and a slot-level kind is a constant — so neither a slot-wide
# stun nor a slot-wide "none" is true of Q, W, E or R, and the walk
# publishes the derived stun schedule on P's own row instead.  (The Annie
# Pyromania rule, per target rather than cross-slot.)
#
# The blocker is the kind alone, never the timing: Slicing Maelstrom
# already lands on the cadence the cache states ("summons a storm around
# himself for 3 seconds", striking "every 0.5 seconds" — the six bolts
# ``_slicing_maelstrom`` authors), so R's hits reach the event ledger and
# still have nothing true to carry.
MODULE_CC: dict[str, str] = {}

parse_abilities = build_parser(SLOTS, "Kennen", cc_kinds=MODULE_CC)

MODULE_COVERAGE = coverage(no_damage="P")
