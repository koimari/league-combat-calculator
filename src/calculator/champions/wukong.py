"""Wukong: Stone Skin, the empowered attack, and the Cyclone timeline.

Q (Crushing Blow) is a DEBUFF-phase slot: the empowered basic attack's bonus
physical damage plus a percentage armor reduction emitted as a
``target_debuff`` under ``q_armor_reduction``.  The shred lands after the
ability's own damage, so Q's packet always meets full armor and everything
after it meets the reduced armor for three seconds.
P (Stone Skin) is modeled as a ``stat_buff`` of bonus armor the survival side
reads; its health regeneration is not priced.
W (Warrior Trickster) is ``out_of_scope`` on the clone's SWING COUNT, not its
per-hit output.  The damage RATIO is sourced twice, as the entry's only
leveling row and as the binary's ``CloneDamageMod``, while the RATE is sourced
nowhere: the binary carries no clone CharacterRecord at all, so there is no
clone base attack speed for E's bonus to apply to.  Shaco's route past a
missing rate does not transfer, because his clone is commanded and the swing
count is something a player states, while Wukong's attacks on its own, so the
same option would invent the number the game decides.  The copied Cyclone has
no home either: the engine prices one attacker's cast timeline.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, DEBUFF, SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import ability_slot, ranked_slot
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .slotlib import simple_damage
from .source_receipts import load_champion_sources
from .stat_grants import with_attack_speed_window

# Crushing Blow's debuff lasts 3s ("inflict armor reduction for 3
# seconds", wiki prose below) — it is not permanent.
_WUKONG_Q_SPELL = spell_object("MonkeyKing", "MonkeyKingDoubleAttack")
_WUKONG_R_SPELL = spell_object("MonkeyKing", "MonkeyKingSpinToWin")
Q_SHRED_DURATION = data_value(_WUKONG_Q_SPELL, "ShredDuration")
# ROOTED IN THE BINARY (data/bin/characters/monkeyking.bin.json): Strength
# of Stone's cap and the seconds one stack stands are MonkeyKingPassive's
# MaxStacks and StackDuration.
_MK_PASSIVE_SPELL = spell_object("MonkeyKing", "MonkeyKingPassive")
_STONE_SKIN_MAX_STACKS = int(data_value(_MK_PASSIVE_SPELL, "MaxStacks"))
_STONE_SKIN_STACK_SECONDS = data_value(_MK_PASSIVE_SPELL, "StackDuration")


_R_TICK_INTERVAL = data_value(_WUKONG_R_SPELL, "SecondsPerTick")
# Nimbus Strike's bonus attack speed lasts the binary
# MonkeyKingNimbus.AttackSpeedDuration; the cached E prose ("for 5
# seconds") corroborates it.
_E_ATTACK_SPEED_SECONDS = data_value(
    spell_object("MonkeyKing", "MonkeyKingNimbus"), "AttackSpeedDuration"
)


@ability_slot("P")
def _stone_skin(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    base = find_named_leveling(ability, "Per-Level Scaling", 0)
    per_stack = find_named_leveling(ability, "Per-Level Scaling", 1)
    if base is None or per_stack is None:
        return None
    max_stacks, seconds = _STONE_SKIN_MAX_STACKS, _STONE_SKIN_STACK_SECONDS
    base_armor = sum_modifiers(base, ctx.level)
    per_stack_armor = sum_modifiers(per_stack, ctx.level)
    requested = ctx.options.get("stone_skin_stacks")
    entry = damage_entry("Stone Skin", ctx.level, 0.0, 0.0, "physical")
    if requested is None:
        # The innate armor stands whatever the count; the stacks ride the
        # ramp. Armor is not a stat any swing walker carries, so the fight
        # serves the level's time-weighted mean (champions/stat_ramp.py).
        ctx.stats["armor"] = ctx.stat("armor") + base_armor
        entry["stat_buff"] = {"armor": base_armor}
        entry["stat_ramp"] = {
            "per_stack": {"armor": per_stack_armor},
            "max_stacks": max_stacks,
            "stack_duration": seconds,
            "stacks_from_swings": True,
            "stacks_from_ability_casts": True,
            "requested": False,
        }
        entry["detail"] = (
            f"+{base_armor:.2f} innate bonus armor, and +{per_stack_armor:.2f} "
            f"more per Strength of Stone stack, up to {max_stacks} held for "
            f"{seconds:g}s each; the fight walks the attacks and abilities "
            "that stack them"
        )
        return entry
    stacks = min(max(int(requested), 0), max_stacks)
    armor = base_armor + stacks * per_stack_armor
    ctx.stats["armor"] = ctx.stat("armor") + armor
    entry["stat_buff"] = {"armor": armor}
    entry["detail"] = f"{stacks} Strength of Stone stack(s); +{armor:.2f} bonus armor"
    return entry


_stone_skin.phase = BUFF


@ranked_slot
def _crushing_blow(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    bonus = extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", bonus, time_offset=0.0),)
    entry["empowers_next_auto"] = True

    # Armor REDUCTION (not penetration): damage.py shreds target armor
    # after Q's own damage, so the empowered swing itself lands at full
    # armor while everything after it (R ticks, E follow-up, later Q
    # casts) sees the reduced armor — matching in-game.
    shred = extract_value(ability, "Armor Reduction", rank)
    if ctx.option("q_armor_reduction") and shred > 0:
        entry["target_debuff"] = {
            "armor_reduction_percent": shred,
            "duration": Q_SHRED_DURATION,
        }
    entry["detail"] = "bonus damage is attached to the empowered basic attack"
    return entry


_crushing_blow.phase = DEBUFF


@ranked_slot
def _cyclone(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    per_tick = extract_named(
        ability, "Physical Damage Per Tick", rank, ctx.stats, ctx.target
    )
    casts = min(max(int(ctx.option("r_casts")), 1), 2)
    ticks = 8 * casts
    total = per_tick * ticks
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            per_tick,
            count=ticks,
            time_offset=0.0,
            hit_interval=_R_TICK_INTERVAL,
        ),
    )
    entry["detail"] = (
        f"{casts} Cyclone cast(s), eight sourced {_R_TICK_INTERVAL:g}-second ticks each"
    )
    return entry


SLOTS = {
    "P": _stone_skin,
    "Q": _crushing_blow,
    # The W clone's attacks are not a direct cast packet, and their COUNT
    # has no cached rate behind it (see the module docstring), so the slot
    # is intentionally omitted here rather than estimated.
    # One strike on the dash target (the two clone strikes land on *other*
    # enemies), so the single-target row is one hit at the cast; the
    # arrival's attack speed rides the same row as a window.
    "E": with_attack_speed_window(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration=_E_ATTACK_SPEED_SECONDS,
        aside="granted on arrival, placed at the cast.",
    ),
    "R": _cyclone,
}

# Cyclone's staff "deals physical damage every 0.25 seconds to enemies hit,
# and can knock them up once for 0.6 seconds".  Crushing Blow's empowered
# swing only deals damage and "inflict[s] armor reduction" — a resistance
# shred, not control — and Nimbus Strike only strikes.  W is the clone's
# pet timeline (no direct cast packet) and P is the armor buff; neither
# authors a damage part.
MODULE_CC = {"Q": "none", "E": "none", "R": "knockup", "P": "none"}

parse_abilities = build_parser(SLOTS, "Wukong", cc_kinds=MODULE_CC)


OPTIONS = [
    int_option(
        "stone_skin_stacks",
        0,
        minimum=0,
        maximum=_STONE_SKIN_MAX_STACKS,
        label=(
            "Strength of Stone stacks; unset walks the ramp over the attacks "
            "and abilities that stack it and serves its fight mean"
        ),
        derives=True,
        rotation={"role": "self_state", "slot": "P"},
    ),
    bool_option(
        "q_armor_reduction",
        True,
        label="Q armor reduction active",
        rotation={"role": "self_state", "slot": "Q"},
    ),
    int_option(
        "r_casts",
        1,
        minimum=1,
        maximum=2,
        label="Cyclone casts",
        rotation={"role": "self_state", "slot": "R"},
    ),
]

ASSUMPTIONS = [
    "Stone Skin armor uses explicit Strength of Stone stacks; regeneration is a "
    "separate survival effect.",
    "Crushing Blow exposes its bonus packet and attaches the next basic attack "
    "through the shared empowered-auto path.",
    "Q's armor reduction (10-30% of target's armor by rank, 3s) applies "
    "to damage dealt after the empowered attack lands, not to the attack "
    "itself.",
    "E (Nimbus Strike) places its arrival's bonus attack speed as a "
    "5-second window at the first E cast; the second window a 7-second "
    "cooldown earns in a longer fight is not placed.",
    "Warrior Trickster's clone is out_of_scope on its SWING COUNT, not on "
    "its output: the 'Clone Outgoing Damage' ratio (40/45/50/55/60%) is the "
    "slot's only cached leveling row, but no clone attack rate is stated "
    "anywhere in the cache, so the number of autonomous attacks over the "
    "clone's 4 seconds cannot be sourced. The Shaco-R route (make the count "
    "an explicit player option) does not apply, because that clone is "
    "commanded and this one is not, so a count would be invented rather "
    "than read; the copied Cyclone would need a second attacker's cast "
    "timeline, which the engine does not have.",
    "Cyclone uses eight sourced 0.25-second ticks per cast; the second cast is explicit.",
]

SOURCES = load_champion_sources("Wukong")
