"""Udyr — CP10.9 full-entry-reviewed packet module.

E1/E2: W Iron Mantle heal streams and R Wingborne Storm 8-tick total are
modeled (healing.py + this module's packet timing declaration); the W shield is
emitted by the ally-support scanner from the cached Shield Strength row.

P1-2 fix — Q (Wilding Claw) becomes a modeled ONHIT slot.  The stance
empowers the next ``q_empowered_attacks`` basic attacks (default 2,
wiki prose) with the sourced on-hit payload: the stance's "Bonus
Physical Damage" row (3% : 8% by rank of the target's maximum health +
3.5% per 100 bonus AD) plus the 4-second "Bonus Physical Damage
On-Hit" row (6 : 36 by rank + 20% bonus AD + 1% : 2% by rank of bonus
health).  With ``q_awaken`` (default False) the Awaken recast adds the
per-level "Max Health Damage" row (2% : 4.24% by level + 1.5% per 100
bonus AD + 0.1% per 100 bonus health) to the empowered attacks, and
each empowered attack's lightning chain is priced as 6 magic strikes at
the sourced 0.2-second cadence (per-strike row 1.5% : 3.18% by level +
0.6% per 100 AP of the target's maximum health; all six chain onto the
single target).

The cache's Q "Heal" row (40 : 174.12 by level) is the lightning
strike's minimum damage against MINIONS (wiki prose), not a self-heal;
the Awaken self-heal family is the W stance stream, which the healing
rule already models.

Coverage: P (Bridge Between) is the stance and Awaken system itself and
E (Blazing Stampede) is a stance stun with movement speed. Transform and
CC magnitude are axes the engine does not have, so both slots are out of
scope; the stances' own damage is priced on Q/W/E/R.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .healing_contract import self_healing_rule
from .inputs import target_stat
from .engine import ONHIT, SlotCtx
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    extract_named,
    extract_value,
    find_named_leveling,
    resolve_scaling,
    with_control_event,
)
from .module_contract import coverage

# HARDCODED: verify on patch updates — wiki Q prose, not JSON:
# the stance empowers the next two basic attacks; the Awaken lightning
# chain fires 6 strikes per empowered attack at 0.2-second intervals.
_Q_EMPOWERED_ATTACKS_DEFAULT = 2
_Q_LIGHTNING_STRIKES_PER_ATTACK = 6
_Q_LIGHTNING_HIT_INTERVAL = 0.2

PACKET_SHA256 = "468fd3bf2d2dd7e836b89c0ae6eff50d844990c0c03442f7f864a2032525dd9c"


def _target_max_health_percent(
    ability: dict[str, Any],
    attribute: str,
    level: int,
    stats: dict[str, float],
    target: dict[str, float],
    *,
    occurrence: int = 0,
) -> float:
    """Resolve a per-level '%' row as '% of the target's maximum health'.

    The scraper stored the Awaken rows' leading unit as bare "%" (the
    "of the target's maximum health" suffix was dropped), so the generic
    resolver prices them as flat.  This reads the row at champion level
    and resolves the leading modifier against the target's max health;
    the remaining modifiers ("% per 100 bonus AD"/"AP"/"bonus health")
    go through the ordinary scaling layer.
    """
    leveling = find_named_leveling(ability, attribute, occurrence)
    if leveling is None:
        raise ValueError(f"Udyr Q {attribute!r} leveling row is unavailable")
    total = 0.0
    index = min(max(level - 1, 0), 19)
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(index, len(values) - 1)
        value = float(values[idx])
        unit = units[idx] if idx < len(units) else ""
        stripped = unit.strip()
        if stripped == "%":
            total += value / 100.0 * float(target_stat(target, "target_max_health"))
        else:
            total += resolve_scaling(unit, value, stats, target)
    return total


def _wilding_claw(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the stance's empowered-attack on-hit (+ Awaken rows)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    awaken = bool(ctx.option("q_awaken"))
    empowered = min(
        max(
            int(ctx.options.get("q_empowered_attacks", _Q_EMPOWERED_ATTACKS_DEFAULT)), 0
        ),
        _Q_EMPOWERED_ATTACKS_DEFAULT,
    )

    stance_bonus = extract_named(
        ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target
    )
    on_hit_flat = extract_named(
        ability, "Bonus Physical Damage On-Hit", rank, ctx.stats, ctx.target
    )
    per_hit = stance_bonus + on_hit_flat
    detail = (
        f"Claw Stance: {empowered} empowered basic attack(s) at "
        f"Bonus Physical Damage ({stance_bonus:g}, % max health + 3.5% per "
        f"100 bonus AD) + Bonus Physical Damage On-Hit ({on_hit_flat:g}, "
        "flat + 20% bonus AD + % bonus health)"
    )

    parts: tuple[DamagePart, ...] = ()
    if awaken:
        max_hp_bonus = _target_max_health_percent(
            ability, "Max Health Damage", ctx.level, ctx.stats, ctx.target
        )
        per_hit += max_hp_bonus
        lightning_per_strike = _target_max_health_percent(
            ability,
            "Per-Level Scaling",
            ctx.level,
            ctx.stats,
            ctx.target,
            occurrence=1,
        )
        strikes = _Q_LIGHTNING_STRIKES_PER_ATTACK * empowered
        parts = (
            DamagePart(
                "magic",
                lightning_per_strike,
                count=strikes,
                time_offset=0.0,
                hit_interval=_Q_LIGHTNING_HIT_INTERVAL,
            ),
        )
        detail += (
            f"; Awaken adds Max Health Damage ({max_hp_bonus:g}, per-level "
            f"% max health) and the lightning chain: {strikes} magic "
            f"strikes at {_Q_LIGHTNING_HIT_INTERVAL:g}s intervals "
            f"({lightning_per_strike:g} each, all chained to the single target)"
        )

    entry = ability_on_hit_entry(
        ability_name(ability),
        rank,
        "physical",
        {
            "name": "Wilding Claw (empowered attack)",
            "damage_per_hit": per_hit,
            "damage_type": "physical",
            "max_procs": empowered,
        },
        cooldown=0.0,
    )
    entry["parts"] = parts
    entry["total_raw"] = per_hit * empowered + sum(
        (part.amount or 0.0) * part.count for part in parts
    )
    entry["detail"] = detail
    return entry


_wilding_claw.phase = ONHIT


def _blazing_stampede(packet_e):
    """E: movement + a sourced stun — a zero-enemy-damage stance row.

    Replaces the packet's generic "no enemy-damage formula" stub text
    with the sourced movement numbers read back out of the cache.  The
    stun itself is not described here: it is authored as a real
    ``ControlEvent`` by the ``with_control_event`` wrapper below, so the
    duration reaches the fight report through the validated atom rather
    than through this string.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_e(ctx)
        if entry is None:
            return None
        ability = ctx.ability()
        rank = ctx.rank_for()
        if ability is None or rank < 1:
            return entry
        burst_ms = extract_value(ability, "Bonus Movement Speed", rank)
        decayed_ms = extract_value(ability, "Decayed Bonus Movement Speed", rank)
        entry["detail"] = (
            "Stampede Stance: no damage row exists in the slot. Ghosting "
            f"plus {burst_ms:g}% bonus movement speed (+5% per 100 bonus AD) "
            f"for 4s, decaying to {decayed_ms:g}% (+1.5% per 100 bonus AD) "
            "over 1.5s; the Awaken recast adds 75 bonus attack range, a "
            "per-level 30% : 41.18% (+10% per 100 bonus AD) movement bonus "
            "and 1.5s of crowd-control immunity. The empowered attack's "
            "0.75s stun IS priced, as a sourced control event. The percent "
            "movement grants are not yet wired onto the shared move-speed "
            "fold (the named percent-movement boundary)."
        )
        return entry

    return parse


def _bridge_between(packet_p):
    """P: stance/cooldown system plus an unmodelable attack-speed steroid.

    Kept ``out_of_scope`` (receipted open, the Olaf-R rule) because Monk
    Training WOULD change damage if it could be modeled.  The row states
    the mechanic and its live blockers instead of pretending the slot is
    non-damaging.

    Three blockers: the windowed path, the cooldown refund, and
    ``buff_window_share``.  All three hold — the windowed kernel in
    ``damage.py`` walks ``cast_order`` and breaks on ``"Q"``.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_p(ctx)
        if entry is None:
            return None
        entry["detail"] = (
            "Awakened Spirit (stance swaps, a 1.5s global cooldown and the "
            "Awaken recast window) carries no damage instance. Monk "
            "Training does move damage and is NOT modeled: after any cast, "
            "the next two basic attacks within 4s gain 30% bonus attack "
            "speed and refund 5% of Awakened Spirit's cooldown (wiki prose "
            "plus the binary's UdyrPassive AttackSpeed calculation 0.30, "
            "AttackSpeedDuration 4.0 and UltCDReduction 0.05). Withheld, "
            "not called no_damage, on three counts. The engine's only "
            "WINDOWED attack-speed path resolves its window start by "
            "walking cast_order to the Q slot, so it is Q-slot-only (the "
            "Miss Fortune W precedent) and a P-slot steroid cannot reach "
            "it. The unwindowed self-buff channel "
            "(module_helpers.buff_window_share) weights a bonus purely by "
            "TIME, while this window is bounded by attack count as well as "
            "time — it closes on the second empowered attack or at 4s, "
            "whichever comes first — so a time-weighted share would "
            "over-credit it whenever the attacks land early. And the "
            "cooldown refund has no engine channel at all (the one "
            "per-attack refund path is item_effects' CooldownProcEffect, "
            "read only by the item-proc scheduler)."
        )
        return entry

    return parse


# Reviewed crowd control, read from the cached kit: R (Wingborne Storm)
# "summons a blizzard around himself for 4 seconds that deals magic damage
# every 0.5 seconds to nearby enemies and slows them while they remain
# within" (the Awakened storm "slows by an additional 5%").  Q rides the
# attack stream as an on-hit payload and W is a shield; E (Blazing
# Stampede) deals no damage of its own, so its stun is not a part kind —
# it is published as a standalone sourced ControlEvent by the
# ``with_control_event`` wrapper below (the Rammus-E shape).
# E (Blazing Stampede) prices no damage of its own; its reviewed stun rides
# the entry as a sourced ControlEvent read off the slot's prose atom.
MODULE_CC = {"E": "stun", "R": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Udyr",
    PACKET_SHA256,
    assumption_overrides=(
        "Wingborne Storm prices all 8 blizzard ticks (Magic Damage per Tick "
        "x 8 == Total Magic Damage) at 0.5-second intervals over 4 seconds.",
    ),
    slot_parsers={
        "R": repeat_damage_parser(
            attr="Magic Damage per Tick",
            dmg_type="magic",
            count=8,
            time_offset=0.5,
            hit_interval=0.5,
            dot_duration=4.0,
        ),
        "Q": _wilding_claw,
    },
    slot_wrappers={
        # The Rammus-E shape: a utility-only slot still publishes its one
        # sourced control event, read through the validated atom catalog.
        "E": lambda parser: with_control_event(
            _blazing_stampede(parser),
            duration_attr="Stun Duration",
            time_offset=None,
        ),
        "P": _bridge_between,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Wilding Claw) empowers q_empowered_attacks (default 2) basic "
    "attacks with the sourced on-hit payload: Bonus Physical Damage "
    "(3% : 8% by rank of the target's maximum health + 3.5% per 100 bonus "
    "AD) plus the 4-second Bonus Physical Damage On-Hit (6 : 36 by rank + "
    "20% bonus AD + 1% : 2% by rank of bonus health).",
    "q_awaken (default False) adds the per-level Max Health Damage row "
    "(2% : 4.24% by level + 1.5% per 100 bonus AD + 0.1% per 100 bonus "
    "health) to the empowered attacks and prices each empowered attack's "
    "lightning chain as 6 magic strikes at the sourced 0.2s cadence "
    "(1.5% : 3.18% by level + 0.6% per 100 AP of the target's maximum "
    "health per strike; all six chain onto the single target).",
    "The cache's Q 'Heal' row (40 : 174.12 by level) is the lightning "
    "strike's minimum damage against minions, not a self-heal; the Awaken "
    "self-heal family is the W stance stream, which healing.py models.",
    "W (Iron Mantle) shield (Shield Strength 45 : 145 by rank + 50% bonus "
    "AD + 40% AP + 2% : 3.5% by rank maximum health) is emitted by the "
    "ally-support scanner at the W cast.",
]
OPTIONS.append(
    {
        "key": "q_awaken",
        "type": "bool",
        "default": False,
        "label": "Q Awaken recast (empowered attacks + lightning)",
    }
)
OPTIONS.append(
    {
        "key": "q_empowered_attacks",
        "type": "int",
        "default": _Q_EMPOWERED_ATTACKS_DEFAULT,
        "min": 0,
        "max": _Q_EMPOWERED_ATTACKS_DEFAULT,
        "label": "Q empowered basic attacks",
    }
)
ASSUMPTIONS = ASSUMPTIONS + [
    "E (Blazing Stampede) is a sourced zero-damage row (MODULE_COVERAGE: "
    "no_damage, reclassified from out_of_scope). Its empowered attack IS "
    "priced as a sourced control event: a 0.75s stun from the validated "
    "timing.control_duration atom, corroborated by the binary's UdyrE "
    "StunDuration 0.75. It is published at cast_boundary precision "
    "(time_offset=None) because the stun rides the next empowered basic "
    "attack and no cast-to-hit delay is sourced, and once per cast "
    "because the sourced on-target cooldown exceeds the window. The "
    "percent movement grants are not published as a stat_buff (the named "
    "Naafiri-W / Sivir-R boundary), and nothing damage-relevant is left "
    "unmodeled once the stun is authored.",
    "P (Bridge Between) stays out_of_scope, not no_damage (the Olaf-R "
    "rule): Monk Training's 30% bonus attack speed on the next two "
    "attacks within 4s is a real sourced steroid that would change "
    "damage (wiki prose plus the binary's UdyrPassive AttackSpeed "
    "calculation 0.30, AttackSpeedDuration 4.0, UltCDReduction 0.05). It "
    "is withheld because the engine's only windowed attack-speed path "
    "resolves its window start from the Q slot (the Miss Fortune W "
    "precedent), because the unwindowed self-buff channel weights purely "
    "by time whereas this window is bounded by attack count as well, and "
    "because the cooldown refund has no engine channel.",
]
MODULE_COVERAGE = coverage(no_damage="E", out_of_scope="P")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Udyr self-healing events from its authored packet."""
    healing = []
    w_rank = _healing.parsed_rank(ability_damages, "W")
    per_tick = _healing.extract_named(
        _healing.ability_json(champion_data, "W"),
        "Heal per Tick",
        w_rank,
        champion_stats,
    )
    if per_tick > 0.0:
        for cast in cast_timeline or []:
            if cast.get("slot") != "W":
                continue
            start = float(cast.get("time", 0.0))
            for index in range(1, 17):
                healing.append(
                    {
                        "time": start + index * 0.25,
                        "amount": float(per_tick),
                        "source": "Iron Mantle",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )
    return healing


SELF_HEALING_RULE = self_healing_rule("Udyr")(derive_self_healing)
