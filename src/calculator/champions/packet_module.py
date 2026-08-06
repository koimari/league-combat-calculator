"""Shared runtime for explicit, source-receipted Wiki/Axword champion packets.

Each champion module selects its own packet specification at build time.
This helper only evaluates those already-selected formulas; it does not
inspect attributes or choose an archetype at runtime.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage

_ROOT = Path(__file__).resolve().parents[3]
_PACKET_PATH = _ROOT / "static" / "reviewed-packets.json"

# Packet JSON stays generator-owned.  These narrowly scoped state boundaries
# are runtime metadata for generated modules whose cached numeric packet is
# valid but whose sibling mechanic needs an explicit scenario state.
_PACKET_ASSUMPTION_OVERRIDES: dict[str, tuple[str, ...]] = {
    "Viego": (
        "Viego Q's mark-consuming second strike requires a prior damaging "
        "ability and the next marked basic attack; that stateful rider is not "
        "modeled by the single-target packet.",
    ),
    "Warwick": (
        "Warwick Q's sourced 0.264-second bite delay is applied to the hit "
        "event without inventing a channel lockout.",
    ),
    "Poppy": (
        "Poppy Q's sourced Hammer Shock field ruptures 1 second after impact; "
        "the packet emits both physical hits.",
    ),
    # E2-3: DoT/channel tick counts are priced per the wiki's Total rows.
    "Skarner": (
        "Shattered Earth prices all three empowered basic attacks "
        "(Bonus Physical Damage per Hit x 3 == Total Bonus Physical Damage).",
    ),
    "Teemo": (
        "Noxious Trap prices the full 4-second poison: 4 ticks of Magic "
        "Damage per Tick (== Total Magic Damage) at 1-second intervals.",
    ),
    "Trundle": (
        "Subjugate prices the full 4-second drain: Magic Damage Per Second "
        "x 8 == Total Magic Damage / Total Healing at every rank.",
    ),
    "Udyr": (
        "Wingborne Storm prices all 8 blizzard ticks (Magic Damage per Tick "
        "x 8 == Total Magic Damage) at 0.5-second intervals over 4 seconds.",
    ),
    "Viktor": (
        "Arcane Storm prices the impact plus the full 6.5-second storm "
        "(Magic Damage + 6 x Magic Damage Per Tick == Total Magic Damage).",
    ),
    "Vladimir": (
        "Sanguine Pool prices all 4 pool ticks (Magic Damage Per Tick x 4 "
        "== Total Magic Damage) at 0.5-second intervals over 2 seconds.",
    ),
    "Xayah": (
        "Double Daggers prices both daggers (Physical Damage Per Hit x 2 "
        "== Total Physical Damage).",
    ),
    "Yuumi": (
        "Final Chapter prices all 5 waves (Magic Damage per Hit + 4 x "
        "Reduced Damage per Hit == Total Magic Damage).",
    ),
    "Zaahen": (
        "The Darkin Glaive prices both strikes (Physical Damage per Hit x 2 "
        "== Total Physical Damage).",
    ),
    "Zac": (
        "Let's Bounce! prices the initial bounce plus 3 reduced bounces "
        "(Magic Damage Per Hit + 3 x Reduced Damage Per Hit == Total Magic "
        "Damage).",
    ),
    "Zeri": (
        "Burst Fire prices all 7 rounds (Physical Damage per Hit x 7 == "
        "Total Physical Damage).",
    ),
}

# These packets are authored as one target hit, including their dynamic
# target-health term.  Keep the certification list explicit: a generic
# packet must not become exact merely because it happens to have one part.
_SINGLE_HIT_EVENT_PACKETS = {
    ("Hwei", "Q"),
    ("Viego", "Q"),
    ("Warwick", "Q"),
    ("Garen", "R"),
    ("Gragas", "W"),
    ("Jax", "E"),
    ("Jinx", "R"),
    ("Singed", "E"),
    ("Sion", "W"),
    ("Volibear", "E"),
    ("Xin Zhao", "R"),
    ("Yone", "W"),
    ("Rek'Sai", "R"),
}

# ---------------------------------------------------------------------------
# E2-3: sourced DoT/channel tick counts (per-tick x ticks == "Total ...").
#
# Each cached packet below carries the wiki's PER-TICK / PER-HIT value and
# the fight used to price ONE tick.  The wiki cache carries a matching
# "Total ..." leveling row, and the tick count is the sourced
# Total/per-tick ratio at every rank (data/champions.json leveling rows,
# locked by tests/test_e2_dot_3.py).  Where the ability is a channel with a
# stated cadence, tick timing comes from the ability's own description text
# ("every 0.5 seconds over the duration", "every second over the next 4
# seconds", "5 magical waves" over a 3.5-second channel, ...).
# ---------------------------------------------------------------------------


def _repeat_damage_parser(
    *,
    attr: str,
    dmg_type: str,
    count: int,
    time_offset: float = 0.0,
    hit_interval: float = 0.0,
    dot_duration: float | None = None,
    name: str | None = None,
):
    """One per-tick attribute priced ``count`` times (E2-3 repeat fix).

    ``per_tick * count`` equals the wiki's "Total ..." row at every rank;
    the parts keep the per-tick amount and emit one event per tick.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.rank_for()
        if rank < 1:
            return None
        per_tick = extract_named(ability, attr, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank),
            per_tick * count,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(
                dmg_type,
                amount=per_tick,
                count=count,
                time_offset=time_offset,
                hit_interval=hit_interval,
            ),
        )
        if dot_duration is not None:
            # Ability damage continues past the cast (poison/zone ticks):
            # item burns stay refreshed for the tail (the Cassiopeia rule).
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = "damage"
    return parse


def _initial_plus_ticks_parser(
    *,
    initial_attr: str,
    tick_attr: str,
    dmg_type: str,
    tick_count: int,
    time_offset: float,
    hit_interval: float,
    dot_duration: float | None = None,
    name: str | None = None,
):
    """One impact hit plus ``tick_count`` channel ticks (Viktor R).

    ``initial + tick_count * per_tick`` equals the wiki's "Total Magic
    Damage" row at every rank (impact + 6 storm bolts for Arcane Storm).
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.rank_for()
        if rank < 1:
            return None
        initial = extract_named(ability, initial_attr, rank, ctx.stats, ctx.target)
        per_tick = extract_named(ability, tick_attr, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank),
            initial + per_tick * tick_count,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(dmg_type, amount=initial, time_offset=0.0),
            DamagePart(
                dmg_type,
                amount=per_tick,
                count=tick_count,
                time_offset=time_offset,
                hit_interval=hit_interval,
            ),
        )
        if dot_duration is not None:
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = "damage"
    return parse


def _full_plus_reduced_parser(
    *,
    full_attr: str,
    reduced_attr: str,
    dmg_type: str,
    reduced_count: int,
    time_offset: float,
    hit_interval: float,
    dot_duration: float | None = None,
    name: str | None = None,
):
    """One full-strength hit plus ``reduced_count`` reduced hits.

    The wiki's "Total ..." row equals ``full + reduced_count * reduced``
    at every rank (Zac's initial bounce + 3 half bounces; Yuumi's first
    wave + 4 waves at 25% damage).
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.rank_for()
        if rank < 1:
            return None
        full = extract_named(ability, full_attr, rank, ctx.stats, ctx.target)
        reduced = extract_named(ability, reduced_attr, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank),
            full + reduced * reduced_count,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(dmg_type, amount=full, time_offset=0.0),
            DamagePart(
                dmg_type,
                amount=reduced,
                count=reduced_count,
                time_offset=time_offset,
                hit_interval=hit_interval,
            ),
        )
        if dot_duration is not None:
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = "damage"
    return parse


# Packet-kind slots replaced by their E2-3 tick parsers.  Key: (champion,
# slot).  Values are traced to data/champions.json leveling rows; the
# counts are the sourced Total/per-tick ratios (see the worklist rows in
# tests/test_e2_dot_3.py).
_E2_PACKET_TICK_PARSERS: dict[tuple[str, str], Any] = {
    # Teemo R — Noxious Trap: "takes magic damage every second over 4
    # seconds" -> 4 ticks; Total Magic Damage 200/325/450 == 4 x per tick.
    ("Teemo", "R"): _repeat_damage_parser(
        attr="Magic Damage per Tick",
        dmg_type="magic",
        count=4,
        time_offset=1.0,
        hit_interval=1.0,
        dot_duration=4.0,
    ),
    # Vladimir W — Sanguine Pool: "magic damage every 0.5 seconds over
    # the duration" (2 seconds) -> 4 ticks; Total == 4 x per tick.
    ("Vladimir", "W"): _repeat_damage_parser(
        attr="Magic Damage Per Tick",
        dmg_type="magic",
        count=4,
        time_offset=0.5,
        hit_interval=0.5,
        dot_duration=2.0,
    ),
    # Udyr R — Wingborne Storm: "for 4 seconds ... every 0.5 seconds" ->
    # 8 ticks; the cached packet base was stale, so the per-tick leveling
    # row is read live; Total Magic Damage 80..400 == 8 x per tick.
    ("Udyr", "R"): _repeat_damage_parser(
        attr="Magic Damage per Tick",
        dmg_type="magic",
        count=8,
        time_offset=0.5,
        hit_interval=0.5,
        dot_duration=4.0,
    ),
    # Xayah Q — Double Daggers: "barrages two Feathers"; Total Physical
    # Damage 90..210 == 2 x Physical Damage Per Hit.  The second feather
    # trails the first by the sourced 0.1s cast-time second segment.
    ("Xayah", "Q"): _repeat_damage_parser(
        attr="Physical Damage Per Hit",
        dmg_type="physical",
        count=2,
        time_offset=0.0,
        hit_interval=0.1,
    ),
    # Zaahen Q — The Darkin Glaive: "strikes the target twice"; Total
    # Physical Damage 15..75 == 2 x Physical Damage per Hit.  The cached
    # packet base was the recast's Bonus Physical Damage, not the base
    # cast, so the per-hit leveling row is read live.
    ("Zaahen", "Q"): _repeat_damage_parser(
        attr="Physical Damage per Hit",
        dmg_type="physical",
        count=2,
        time_offset=0.0,
        hit_interval=0.0,
    ),
    # Zeri Q — Burst Fire: "fires a burst of 7 rounds"; Total Physical
    # Damage 22..38 == 7 x Physical Damage per Hit (7.01/7.01/6.99/7.0/7.0
    # sourced ratios, the wiki's rounding of 7 rounds).
    ("Zeri", "Q"): _repeat_damage_parser(
        attr="Physical Damage per Hit",
        dmg_type="physical",
        count=7,
        time_offset=0.0,
        hit_interval=0.0,
    ),
    # Viktor R — Arcane Storm: impact + "a bolt ... every second" for the
    # 6.5-second storm -> 6 bolts; Total Magic Damage 490/805/1120 ==
    # Magic Damage (impact) + 6 x Magic Damage Per Tick.
    ("Viktor", "R"): _initial_plus_ticks_parser(
        initial_attr="Magic Damage",
        tick_attr="Magic Damage Per Tick",
        dmg_type="magic",
        tick_count=6,
        time_offset=1.0,
        hit_interval=1.0,
        dot_duration=6.5,
    ),
    # Zac R — Let's Bounce!: "bounces 3 additional times each second over
    # 3 seconds", "ones beyond the first deal 50% damage"; Total Magic
    # Damage 300/475/650 == Per Hit + 3 x Reduced Damage Per Hit.
    ("Zac", "R"): _full_plus_reduced_parser(
        full_attr="Magic Damage Per Hit",
        reduced_attr="Reduced Damage Per Hit",
        dmg_type="magic",
        reduced_count=3,
        time_offset=1.0,
        hit_interval=1.0,
        dot_duration=3.0,
    ),
    # Yuumi R — Final Chapter: "launch 5 magical waves" over the 3.5s
    # channel; "Subsequent waves against enemies hit deal 25% damage";
    # Total Magic Damage 150/250/350 == per Hit + 4 x Reduced Damage per
    # Hit (5 waves at 0.7-second intervals).
    ("Yuumi", "R"): _full_plus_reduced_parser(
        full_attr="Magic Damage per Hit",
        reduced_attr="Reduced Damage per Hit",
        dmg_type="magic",
        reduced_count=4,
        time_offset=0.7,
        hit_interval=0.7,
        dot_duration=3.5,
    ),
}

# Plain wiki-attribute slots replaced by their E2-3 tick parsers.
# Key: (champion, slot).
_E2_WIKI_ATTR_TICK_PARSERS: dict[tuple[str, str], Any] = {
    # Trundle R — Subjugate: the drain lasts 4 seconds; the wiki's "Magic
    # Damage Per Second" display value times 8 equals Total Magic Damage
    # 20/25/30 (% max HP) at every rank (the cached packet priced only the
    # "Initial Magic Damage" half).  The drain is priced as 8 half-second
    # ticks spanning the sourced 4-second window.
    ("Trundle", "R"): _repeat_damage_parser(
        attr="Magic Damage Per Second",
        dmg_type="magic",
        count=8,
        time_offset=0.5,
        hit_interval=0.5,
        dot_duration=4.0,
        name="Subjugate",
    ),
}

# Wiki-attribute variants replaced by their E2-3 tick parsers.  Key:
# (champion, slot, variant index).
_E2_VARIANT_TICK_PARSERS: dict[tuple[str, str, int], Any] = {
    # Skarner Q — Shattered Earth (variant 0): "empowering up to three of
    # his next basic attacks"; Total Bonus Physical Damage 30..150 == 3 x
    # Bonus Physical Damage per Hit.
    ("Skarner", "Q", 0): _repeat_damage_parser(
        attr="Bonus Physical Damage per Hit",
        dmg_type="physical",
        count=3,
        time_offset=0.0,
        hit_interval=0.0,
        name="Shattered Earth",
    ),
}


@lru_cache(maxsize=1)
def _packet_specs() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_PACKET_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Reviewed packet asset is unavailable: {_PACKET_PATH}"
        ) from exc
    champions = payload.get("champions") if isinstance(payload, dict) else None
    if not isinstance(champions, dict):
        raise RuntimeError("Reviewed packet asset has no champion map")
    return champions


def _ranked(values: list[float], rank: int) -> float:
    if not values:
        return 0.0
    return float(values[min(max(rank, 1) - 1, len(values) - 1)])


def _packet_parser(spec: dict[str, Any], slot: str, champion_name: str):
    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.level if spec.get("ranks") == "level" else ctx.rank_for()
        if rank < 1:
            return None

        base = _ranked(spec.get("base", []), rank)
        static = base
        target_terms: list[tuple[str, float]] = []
        for ratio in spec.get("ratios", []):
            stat = str(ratio.get("stat", ""))
            value = _ranked(ratio.get("values", []), rank)
            if stat in {"targetMaxHp", "targetCurrentHp", "targetMissingHp"}:
                target_terms.append((stat, value))
                continue
            stat_key = {
                "ap": "ability_power",
                "ad": "attack_damage",
                "bonusAd": "bonus_attack_damage",
                "health": "health",
                "bonusHealth": "bonus_health",
                "armor": "armor",
                "magicResistance": "magic_resistance",
            }.get(stat)
            if stat_key:
                static += value * float(ctx.stats.get(stat_key, 0.0))

        damage_type = str(spec.get("damage_type", "magic"))
        if target_terms:
            target_max = float(ctx.target.get("target_max_health", 0.0))

            def hp_scaled(missing_ratio: float) -> float:
                current_ratio = max(0.0, 1.0 - missing_ratio)
                total = static
                for kind, value in target_terms:
                    if kind == "targetMaxHp":
                        total += value * target_max
                    elif kind == "targetCurrentHp":
                        total += value * target_max * current_ratio
                    else:
                        total += value * target_max * missing_ratio
                return total

            parts = (DamagePart(damage_type, hp_scaled_damage=hp_scaled),)
            total_raw = static
        else:
            parts = (DamagePart(damage_type, amount=static),)
            total_raw = static

        entry = damage_entry(
            ability.get("name", spec.get("name", f"Ability {slot}")),
            rank,
            float(spec.get("cooldown", 0.0)),
            total_raw,
            damage_type,
        )
        entry["parts"] = parts
        entry["total_raw"] = total_raw
        # Hammer Shock hits on impact and again when its one-second field
        # ruptures.  The cached source exposes both the single-hit damage
        # and the doubled total, so keep the two authored events explicit
        # instead of certifying the packet as a single cast-boundary hit.
        if champion_name == "Poppy" and slot == "Q":
            entry["parts"] = tuple(
                DamagePart(
                    part.damage_type,
                    amount=part.amount,
                    count=2,
                    hp_scaled_damage=part.hp_scaled_damage,
                    time_offset=0.0,
                    hit_interval=1.0,
                )
                for part in parts
            )
            entry["total_raw"] = total_raw * 2
        # Warwick's bite lands 0.264 seconds after the cast starts.  The
        # cached ability notes source this fixed bite delay even though the
        # cast-time field is ``none``; keep the packet's damage event on the
        # bite boundary without inventing a channel lockout.
        if champion_name == "Warwick" and slot == "Q":
            entry["parts"] = tuple(
                DamagePart(
                    part.damage_type,
                    amount=part.amount,
                    count=part.count,
                    hp_scaled_damage=part.hp_scaled_damage,
                    time_offset=0.264,
                    hit_interval=part.hit_interval,
                )
                for part in entry["parts"]
            )
        # Hwei's Devastating Fire has a sourced 0.25-second cast time; the
        # packet's single hit lands at that boundary rather than at cast
        # start.
        if champion_name == "Hwei" and slot == "Q":
            entry["parts"] = tuple(
                DamagePart(
                    part.damage_type,
                    amount=part.amount,
                    count=part.count,
                    hp_scaled_damage=part.hp_scaled_damage,
                    time_offset=0.25,
                    hit_interval=part.hit_interval,
                )
                for part in entry["parts"]
            )
        # A packet can certify a dynamic-health cast when the authored
        # packet is exactly one hit.  The damage engine still evaluates the
        # current target health at the cast boundary; there is no hidden
        # intra-cast ordering left to guess.  Multi-hit packets deliberately
        # keep the conservative cast-boundary marker until their hit timing
        # is sourced separately.
        if (champion_name, slot) in _SINGLE_HIT_EVENT_PACKETS and int(
            spec.get("count", 1)
        ) == 1:
            entry["event_order_certified"] = "single_hit"
        if spec.get("cast_time") is not None:
            entry["cast_time"] = float(spec["cast_time"])
        if spec.get("count", 1) != 1:
            entry["parts"] = tuple(
                DamagePart(
                    part.damage_type,
                    amount=part.amount,
                    count=int(spec["count"]),
                    hp_scaled_damage=part.hp_scaled_damage,
                )
                for part in parts
            )
        return entry

    parse.phase = "damage"
    return parse


def _no_formula_parser(
    slot: str, *, reason: str = "No enemy damage is listed for this ability."
):
    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


def build_packet_module(champion_name: str):
    """Return the explicit parser and metadata for one generated champion."""
    champion = _packet_specs().get(champion_name)
    if champion is None:
        raise KeyError(f"No reviewed packet specification for {champion_name!r}")
    slots = {}
    options: list[dict[str, Any]] = []
    for slot in ("Q", "W", "E", "R", "P"):
        spec = champion.get("slots", {}).get(slot)
        if not spec:
            continue
        variants = spec.get("variants") if spec.get("kind") == "variants" else None
        if variants:
            variant_parsers = []
            for variant_index, variant in enumerate(variants):
                custom = _E2_VARIANT_TICK_PARSERS.get(
                    (champion_name, slot, variant_index)
                )
                if custom is not None:
                    variant_parsers.append(custom)
                elif variant.get("kind") == "wiki_attribute":
                    variant_parsers.append(
                        simple_damage(
                            attr=str(variant["attribute"]),
                            dmg_type=str(variant.get("damage_type", "auto")),
                            ranks=str(variant.get("ranks", "rank")),
                            source=(
                                tuple(variant["source"])
                                if variant.get("source")
                                else None
                            ),
                        )
                    )
                elif variant.get("kind") == "packet":
                    variant_parsers.append(_packet_parser(variant, slot, champion_name))
                else:
                    variant_parsers.append(
                        _no_formula_parser(
                            slot,
                            reason=str(
                                variant.get(
                                    "reason",
                                    "No enemy damage is listed for this variant.",
                                )
                            ),
                        )
                    )
            option_key = f"{slot.lower()}_variant"

            def select_variant(
                ctx: SlotCtx,
                parsers=variant_parsers,
                key=option_key,
                default=spec.get("default", 0),
            ):
                try:
                    index = int(ctx.options.get(key, default))
                except (TypeError, ValueError):
                    index = int(default)
                index = max(0, min(index, len(parsers) - 1))
                return parsers[index](ctx)

            select_variant.phase = getattr(variant_parsers[0], "phase", "damage")
            slots[slot] = select_variant
            options.append(
                {
                    "key": option_key,
                    "type": "int",
                    "default": int(spec.get("default", 0)),
                    "label": f"{slot} packet variant",
                    "min": 0,
                    "max": len(variants) - 1,
                }
            )
        elif spec.get("kind") == "wiki_attribute":
            custom = _E2_WIKI_ATTR_TICK_PARSERS.get((champion_name, slot))
            slots[slot] = (
                custom
                if custom is not None
                else simple_damage(
                    attr=str(spec["attribute"]),
                    dmg_type=str(spec.get("damage_type", "auto")),
                    ranks=str(spec.get("ranks", "rank")),
                    source=tuple(spec["source"]) if spec.get("source") else None,
                )
            )
        elif spec.get("kind") == "packet":
            custom = _E2_PACKET_TICK_PARSERS.get((champion_name, slot))
            slots[slot] = (
                custom
                if custom is not None
                else _packet_parser(spec, slot, champion_name)
            )
        elif spec.get("kind") == "no_damage":
            slots[slot] = _no_formula_parser(
                slot,
                reason=str(
                    spec.get("reason", "No enemy damage is listed for this ability.")
                ),
            )
        else:
            slots[slot] = _no_formula_parser(slot)
    parser = build_parser(slots, champion_name)

    def parse_abilities(*args, **kwargs):
        result = parser(*args, **kwargs)
        for entry in result.values():
            if "parts" in entry:
                continue
            entry["parts"] = ()
            entry.setdefault("total_raw", 0.0)
            on_hit = entry.get("on_hit") or {}
            entry.setdefault("damage_type", on_hit.get("damage_type", "physical"))
        return result

    assumptions = list(champion.get("assumptions", []))
    assumptions.extend(_PACKET_ASSUMPTION_OVERRIDES.get(champion_name, ()))
    sources = list(champion.get("sources", []))
    return parse_abilities, slots, assumptions, sources, options
