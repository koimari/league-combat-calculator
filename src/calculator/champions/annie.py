"""Annie — slot map for the archetype engine.

Why each slot is non-generic:
- R (Summon: Tibbers) is a custom BUFF-phase slot with three parts:
  a % magic-penetration stat buff (mutated into ``ctx.stats`` and
  emitted as ``stat_buff`` — BUFF phase guarantees Q/W parse after it),
  the initial burst ("Initial Magic Damage"), the Tibbers aura, and the
  Tibbers auto attacks.  The aura and auto-attack numbers are NOT in the
  JSON (pet stats are not scraped from the wiki) — they come from the
  wiki's Annie pets entry (see the quarantined constants below).  The
  attacks are emitted as a separate ``tibbers_attacks`` proc row (the R
  cast itself stays burst + aura) so the fight prices them once over
  the window instead of per R cast.
- P (Pyromania) is a cross-slot charge walk shown as a zero-damage row
  under the literal "P" results key (the pre-engine UI shape), so a
  custom slot fn writes it into ``ctx.results`` directly instead of
  using the engine's "P" -> "passive" mapping.  Every cast charges and
  the next Q/W/R cast at the cap spends the charge as a stun, so the
  row reports the charge the walk derives rather than a marker on one
  cast.
- E (Molten Shield) shields, and its second cached effect is the
  retaliation landing: enemies that damage the shield take a sourced
  25/35/45/55/65 (+40% AP), once per enemy per cast.
- Q/W are plain "Magic Damage" attribute reads.

All numeric values are read from the champion JSON data except the
Tibbers aura and auto-attack constants (wiki pets entry).
"""

import re
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx, build_parser
from .inputs import float_option, int_option
from .module_helpers import ability_cast_times, ranked_slot
from .slotlib import (
    ability_name,
    damage_entry,
    effect_description,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    fixed_count_pet_row,
    simple_damage,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — pet stats are not in the JSON.
# Tibbers pet numbers come from the LoL Wiki "Annie#Pets" entry:
# https://wiki.leagueoflegends.com/en-us/Annie
# - Flame Aura ticks every 0.25 seconds; base damage per tick 2/3/4 at
#   R rank 1/2/3; AP ratio per tick 1% AP (0.01).
# - Auto attack: 30 / 45 / 60 (based on R rank) + 10% AP magic damage.
# - Base attack speed 0.625; on summon Tibbers ENRAGES for 3 seconds,
#   attacking at 1.736 AS for his next 5 attacks, decaying with each
#   attack (wiki formula:
#   1.736*(1-(11.505*(x-1)+0.3*((x-2)^3-(x-2))/6+1.7*(x-2)*(x-1)/2)/100)
#   for x = attacks consumed 1..5), then returning to 0.625 AS.
_TIBBERS_AURA_BASE_PER_TICK = [2.0, 3.0, 4.0]
_TIBBERS_AURA_AP_RATIO_PER_TICK = 0.01
_TIBBERS_AURA_TICK_INTERVAL = 0.25
_TIBBERS_AUTO_BASE = [30.0, 45.0, 60.0]
_TIBBERS_AUTO_AP_RATIO = data_value(
    spell_object("Annie", "AnnieR"), "TibbersAttackAPRatio"
)
_TIBBERS_BASE_ATTACK_SPEED = 0.625
_TIBBERS_ENRAGE_SECONDS = data_value(spell_object("Annie", "AnnieR"), "EnrageDuration")
_TIBBERS_ENRAGE_ATTACK_COUNT = 5
_TIBBERS_ENRAGE_BASE_AS = 1.736
_TIBBERS_DEFAULT_WINDOW = 5.0  # one rotation; timed fights pass the real window
_TIBBERS_MAX_ATTACKS = 30


def _tibbers_enrage_attack_speeds() -> tuple[float, ...]:
    """The five enrage attack speeds (attacks per second, wiki formula)."""
    speeds = []
    for consumed in range(1, _TIBBERS_ENRAGE_ATTACK_COUNT + 1):
        decay = (
            11.505 * (consumed - 1)
            + 0.3 * ((consumed - 2) ** 3 - (consumed - 2)) / 6
            + 1.7 * (consumed - 2) * (consumed - 1) / 2
        )
        speeds.append(_TIBBERS_ENRAGE_BASE_AS * (1.0 - decay / 100.0))
    return tuple(speeds)


def _tibbers_attack_times(count: int) -> list[float]:
    """First ``count`` Tibbers auto-attack timestamps from the sourced cadence.

    The enrage attacks land at the five decayed attack speeds, then the
    base 0.625 AS (1.6s interval) takes over.  Timestamps are seconds
    from the summon cast.
    """
    times: list[float] = []
    elapsed = 0.0
    for speed in _tibbers_enrage_attack_speeds():
        elapsed += 1.0 / speed
        times.append(elapsed)
        if len(times) >= count:
            return times
    while len(times) < count:
        elapsed += 1.0 / _TIBBERS_BASE_ATTACK_SPEED
        times.append(elapsed)
    return times


def _tibbers_attacks_row(ctx: SlotCtx, rank: int) -> dict[str, Any] | None:
    """The Tibbers auto-attack proc row (None when the player wants none).

    The default attack count is the sourced cadence (5 enrage attacks
    then the 1.6s base-AS interval) truncated to the fight window; the
    ``tibbers_attacks`` option overrides it — the player steers Tibbers,
    so positioning/leash uptime is a player choice.

    An ``auto_attacks_only`` window casts no R, and R's Active is what
    summons Tibbers, so there is no pet to steer.
    """
    if ctx.option("auto_attacks_only"):
        return None
    window = float(ctx.options.get("fight_duration_seconds", _TIBBERS_DEFAULT_WINDOW))
    requested = ctx.options.get("tibbers_attacks")
    if requested is None:
        attack_count = sum(
            1 for time in _tibbers_attack_times(_TIBBERS_MAX_ATTACKS) if time <= window
        )
    else:
        attack_count = min(max(int(requested), 0), _TIBBERS_MAX_ATTACKS)
    if attack_count <= 0:
        return None
    per_attack = (
        _TIBBERS_AUTO_BASE[min(rank - 1, len(_TIBBERS_AUTO_BASE) - 1)]
        + _TIBBERS_AUTO_AP_RATIO * ctx.stats["ability_power"]
    )
    return fixed_count_pet_row(
        "Tibbers Attacks",
        "magic",
        per_attack,
        _tibbers_attack_times(attack_count),
        detail=(
            f"{attack_count} Tibbers auto attack(s) at {per_attack:.2f} "
            f"magic each (5 enrage attacks, then "
            f"{1.0 / _TIBBERS_BASE_ATTACK_SPEED:.1f}s cadence)"
        ),
    )


@ranked_slot
def _summon_tibbers(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: % magic-pen stat buff + initial burst + Tibbers aura.

    Supports the ``tibbers_aura_seconds`` option (default 5.0) — how
    many seconds of aura damage to include in the R total.
    """

    # R passive: % magic penetration, applied to the shared stats
    # context (BUFF phase runs before every damage slot) and reported
    # via stat_buff for the fight engine.
    magic_pen = extract_value(ability, "Magic Penetration", rank)
    ctx.stats["magic_penetration_percent"] = (
        ctx.stat("magic_penetration_percent") + magic_pen
    )

    burst = extract_named(ability, "Initial Magic Damage", rank, ctx.stats)
    cooldown = extract_cooldown(ability, rank)

    # Tibbers aura damage (not in JSON — wiki constants above).
    aura_seconds = float(ctx.option("tibbers_aura_seconds"))
    aura_base = _TIBBERS_AURA_BASE_PER_TICK[
        min(rank - 1, len(_TIBBERS_AURA_BASE_PER_TICK) - 1)
    ]
    aura_per_tick = (
        aura_base + _TIBBERS_AURA_AP_RATIO_PER_TICK * ctx.stats["ability_power"]
    )
    total_ticks = aura_seconds / _TIBBERS_AURA_TICK_INTERVAL
    aura_total = aura_per_tick * total_ticks

    total = burst + aura_total

    # Tibbers auto attacks: a fixed proc row priced over the fight
    # window, not per R cast (see _tibbers_attacks_row).
    attacks = _tibbers_attacks_row(ctx, rank)
    if attacks is not None:
        ctx.results["tibbers_attacks"] = attacks

    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "magic",
        "parts": (DamagePart("magic", total),),
        "total_raw": total,
        "initial_burst": burst,
        "tibbers_aura": {
            "damage_per_tick": aura_per_tick,
            "total_ticks": total_ticks,
            "aura_total": aura_total,
        },
        "stat_buff": {
            "magic_penetration_percent": magic_pen,
        },
    }


_summon_tibbers.phase = BUFF


# Pyromania is prose only — its cached effects carry no leveling row — so
# the charge cap, the slots that may spend it and the level-stepped stun
# are read from the sentences that state them and raise when a patch stops
# stating them (the Shyvana Scalemail rule).
_STACK_CAP_RE = re.compile(r"stacking up to (\d+) times")
_ENERGIZED_STUN_RE = re.compile(
    r"stun enemies hit for ([\d.]+) / ([\d.]+) / ([\d.]+) \(based on level\)"
)
# HARDCODED: verify on patch updates — against the GAME FILES, because the
# cached entry states "1.25 / 1.5 / 1.75 (based on level)" and names no
# level at all: https://raw.communitydragon.org/latest/game/data/characters/
# annie/annie.bin.json, Characters/Annie/Spells/AnniePassiveAbility/
# AnniePassive -> mSpellCalculations.StunDuration, a
# ByCharLevelBreakpointsCalculationPart with mLevel1Value 1.25 and
# mBreakpoints at mLevel 6 and mLevel 11 (+0.25 each).  The same record's
# MaxStacks 4 corroborates the charge cap the innate's sentence states.
# Descending, so the walk takes the first breakpoint the level clears.
_STUN_BREAKPOINT_LEVELS = (11, 6, 1)
_CHARGE_EFFECT = 0
_ENERGIZED_EFFECT = 1
#: Molten Shield retaliates "once per enemy per cast", so a Summoner's Rift
#: team is the most landings one cast can ever have.
_MAX_RETALIATIONS = 5


def _charge_cap(ability: dict[str, Any]) -> int:
    """Pyromania's stack cap, from the sentence that states it."""
    match = _STACK_CAP_RE.search(effect_description(ability, _CHARGE_EFFECT))
    if match is None:
        raise ValueError(
            "Annie P: the cached Pyromania innate no longer states "
            "'stacking up to N times', so the charge cap has no source"
        )
    return int(match.group(1))


def _stun_seconds(ability: dict[str, Any], level: int) -> float:
    """The Energized stun at a champion level, from the cached sentence."""
    match = _ENERGIZED_STUN_RE.search(effect_description(ability, _ENERGIZED_EFFECT))
    if match is None:
        raise ValueError(
            "Annie P: the cached Energized effect no longer states "
            "'stun enemies hit for A / B / C (based on level)'"
        )
    steps = [float(value) for value in match.groups()]
    for seconds, breakpoint_level in zip(
        reversed(steps), _STUN_BREAKPOINT_LEVELS, strict=False
    ):
        if level >= breakpoint_level:
            return seconds
    return steps[0]


def _energized_spenders(ctx: SlotCtx, ability: dict[str, Any]) -> frozenset[str]:
    """The slots the Energized sentence names as spenders (Q, W and R).

    Molten Shield charges Pyromania like every other cast but is absent
    from "her next cast of Disintegrate, Incinerate, or Summon: Tibbers",
    so the spender set is read off the cached ability names rather than
    written down a second time.
    """
    sentence = effect_description(ability, _ENERGIZED_EFFECT)
    spenders = frozenset(
        slot
        for slot in ("Q", "W", "E", "R")
        if (named := ctx.ability(slot)) is not None and ability_name(named) in sentence
    )
    if not spenders:
        raise ValueError(
            "Annie P: the cached Energized effect names no ability this kit "
            "has, so no slot can be said to spend the charge"
        )
    return spenders


def _pyromania(ctx: SlotCtx) -> None:
    """P: walk the fight's own casts through the cross-slot charge.

    Every Q/W/E/R cast adds a stack; at the cap the next cast of a
    spender slot consumes the whole charge and stuns.  ``pyromania_stacks``
    is the opening charge — the one thing no walk can derive, because it
    depends on what Annie cast before the fight (the cached innate opens
    her at the cap on spawn).  The row is written into ``ctx.results``
    because its home is the literal "P" key, not the "passive" a return
    maps to.
    """
    ability = ctx.ability()
    if ability is None:
        return
    cap = _charge_cap(ability)
    stun = _stun_seconds(ability, ctx.level)
    opening = min(max(int(ctx.option("pyromania_stacks")), 0), cap)
    spenders = _energized_spenders(ctx, ability)
    window = ctx.options.get("fight_duration_seconds")
    stacks = opening
    stun_times: list[float] = []
    if window is not None:
        for time, slot in ability_cast_times(ctx, float(window), ("Q", "W", "E", "R")):
            if stacks >= cap and slot in spenders:
                stun_times.append(time)
                stacks = 0
            else:
                stacks = min(stacks + 1, cap)
    entry = damage_entry(ability_name(ability), 0, 0.0, 0.0, "magic")
    entry["detail"] = (
        f"{len(stun_times)} Energized stun(s) of {stun:g}s "
        f"(charge {opening}/{cap} at the opening, {stacks}/{cap} at the end); "
        + (
            "stuns at " + ", ".join(f"{time:.2f}s" for time in stun_times)
            if stun_times
            else f"the charge is spent by the next {'/'.join(sorted(spenders))} cast"
        )
    )
    ctx.results["P"] = entry


@ranked_slot
def _molten_shield(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: the shield's sourced retaliation landing.

    "While Molten Shield is active, enemies that deal damage to it take
    magic damage ... once per enemy per cast" is a real cached leveling
    row, so the entry prices ``e_shield_retaliations`` landings of it.
    The default is zero: the pair engine's target deals Annie no damage,
    the same answer a thorns item gives in a fight with no incoming
    attacks.  One landing is a certified single hit; several are one
    aggregate, because nothing sources when each enemy strikes.
    """
    if find_named_leveling(ability, "Magic Damage") is None:
        raise ValueError(
            "Annie E: the cached Molten Shield entry no longer carries a "
            "'Magic Damage' leveling row for its retaliation"
        )
    per_enemy = extract_named(ability, "Magic Damage", rank, ctx.stats)
    hits = min(max(int(ctx.option("e_shield_retaliations")), 0), _MAX_RETALIATIONS)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_enemy * hits,
        "magic",
        event_order_certified="single_hit" if hits == 1 else None,
    )
    if hits > 1:
        entry["parts"] = (DamagePart("magic", per_enemy, count=hits),)
    entry["detail"] = (
        f"{hits} retaliation landing(s) at {per_enemy:.2f} magic each "
        "(once per enemy per cast, while the shield holds)"
    )
    return entry


OPTIONS = [
    float_option(
        "tibbers_aura_seconds",
        5.0,
        minimum=0,
        maximum=45,
        label="Tibbers aura duration (seconds)",
        step=0.5,
    ),
    int_option(
        "tibbers_attacks",
        5,
        minimum=0,
        maximum=30,
        label="Tibbers auto attacks (0 = none; defaults to the fight "
        "window at the sourced enrage + 0.625 AS cadence)",
    ),
    int_option(
        "pyromania_stacks",
        4,
        minimum=0,
        maximum=4,
        label="Pyromania charge at the opening (4 = Energized, the cached "
        "innate's state on spawn)",
    ),
    int_option(
        "e_shield_retaliations",
        0,
        minimum=0,
        maximum=_MAX_RETALIATIONS,
        label="Enemies that damage Molten Shield (once per enemy per cast)",
    ),
]

ASSUMPTIONS = [
    "R magic penetration passive is always active",
    "E (Molten Shield) shields Annie for the sourced 60/95/130/165/200 "
    "+ 40% AP (cached Shield Strength row) for the typed active-duration "
    "atom at the cast; the ally-support scanner emits the packet and it "
    "absorbs incoming damage in the participant ledger",
    "Tibbers auto attacks are priced at the wiki pets cadence (5 enrage "
    "attacks from the summon, then the 0.625 base AS) truncated to the "
    "fight window; positioning/leash uptime is a player choice via the "
    "tibbers_attacks option",
    "An autos-only fight has no Tibbers at all (the pipeline states this "
    "with the auto_attacks_only reserved option): the cached R text "
    "sources him to 'Active: Annie summons Tibbers to the target "
    "location', which no basic attack performs. R's magic-penetration "
    "passive is innate and still applies",
    "Tibbers aura defaults to 5 seconds of damage",
    "The Pyromania charge walks the fight's own cast stream at the "
    "Braum-pattern schedule (each learned slot at t=0 and every hasted "
    "cooldown after); the empowered cast consumes the whole charge and "
    "starts recharging from zero, and an autos-only window casts nothing, "
    "so the charge never moves",
    "E retaliation lands only when the scenario declares enemies hitting "
    "the shield (e_shield_retaliations, default 0): who strikes Annie and "
    "when is not something the one-pair fight sources",
]

SLOTS = {
    "R": _summon_tibbers,
    "P": _pyromania,
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _molten_shield,
}

# MODULE_CC is empty, and the Pyromania walk is why rather than an excuse
# for it.  The charge is cross-slot: every cast adds one and the next
# Disintegrate, Incinerate or Summon: Tibbers at the cap "consume[s] all
# Pyromania stacks to stun enemies hit".  Which casts of a slot are the
# empowered ones is therefore a property of the fight's cast stream, and a
# slot-level kind is a constant — so neither a slot-wide stun nor a
# slot-wide "none" is true of Q, W or R, and the walk publishes the derived
# stun schedule on P's own row instead.  E only makes "enemies that deal
# damage to it take magic damage", which is no control at all, but its
# aggregate landing row has no per-hit boundary for a marker to ride.
# (Kennen's Mark of the Storm is the same shape, per target.)
MODULE_CC: dict[str, str] = {}

parse_abilities = build_parser(SLOTS, "Annie", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Annie")
