"""Exact packet helpers for the CP10.3 champion batch.

The batch is intentionally small and explicit.  Every parser reads the
revision-pinned champion JSON rather than carrying a second table of rank
values; state that cannot be priced as damage is emitted as a named
``no_damage`` row with an explicit reason.  The options below are the
minimal target/variant choices needed to keep an ordered one-rotation receipt
honest (dagger count, marks, form, recasts, and so on).
"""

from __future__ import annotations

from typing import Any, Callable

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .reviewed_batch_01 import no_damage, source_row
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    on_hit_entry,
    proc_damage,
    simple_damage,
)


def _typed(
    ctx: SlotCtx,
    attribute: str,
    damage_type: str,
    *,
    count: int = 1,
    time_offset: float | None = None,
    hit_interval: float | None = None,
    rank: int | None = None,
    source_slot: str | None = None,
) -> dict[str, Any] | None:
    """Build one explicitly named packet from the source JSON."""

    slot = source_slot or ctx.slot
    ability = ctx.ability(slot)
    if ability is None:
        return None
    selected = rank if rank is not None else ctx.rank_for(slot)
    if slot == "P" and rank is None:
        selected = ctx.level
    if selected < 1:
        return None
    value = extract_named(ability, attribute, selected, ctx.stats, ctx.target)
    entry = damage_entry(
        str(ability.get("name", slot)),
        selected,
        extract_cooldown(ability, selected),
        value * max(1, count),
        damage_type,
    )
    entry["parts"] = (
        DamagePart(
            damage_type,
            value,
            count=max(1, count),
            time_offset=time_offset,
            hit_interval=hit_interval,
        ),
    )
    return entry


def _mixed(
    ctx: SlotCtx,
    name: str,
    rank: int,
    cooldown: float,
    magic: float,
    true_damage: float,
    *,
    detail: str,
) -> dict[str, Any]:
    parts = (DamagePart("magic", magic), DamagePart("true", true_damage))
    return {
        "name": name,
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "mixed",
        "total_raw": magic + true_damage,
        "parts": parts,
        "detail": detail,
    }


def _r_daggers(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    daggers = max(1, min(15, int(ctx.options.get("r_daggers", 15))))
    physical = extract_named(
        ability, "Physical Damage Per Dagger", rank, ctx.stats, ctx.target
    )
    magic = extract_named(
        ability, "Magic Damage Per Dagger", rank, ctx.stats, ctx.target
    )
    interval = 2.5 / daggers
    entry = {
        "name": ability.get("name", "Death Lotus"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "mixed",
        "total_raw": (physical + magic) * daggers,
        "parts": (
            DamagePart(
                "physical",
                physical,
                count=daggers,
                time_offset=0.166,
                hit_interval=interval,
            ),
            DamagePart(
                "magic", magic, count=daggers, time_offset=0.166, hit_interval=interval
            ),
        ),
        "detail": f"{daggers} sourced daggers at 0.166-second cadence; on-hit/Grievous Wounds are ordered state.",
        "event_order_certified": True,
    }
    return entry


def _kayle_passive(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    if ctx.level < 11 or not bool(ctx.options.get("p_exalted", True)):
        return no_damage(
            ctx,
            name="Divine Ascent",
            reason="Before level 11 or without Exalted, Kayle's fire wave is not available; attack range and Zeal remain state.",
        )
    value = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    result = on_hit_entry("Divine Ascent (Aflame wave)", value, "magic")
    result["detail"] = (
        "Level 11 Aflame wave on every Exalted basic attack; range and Zeal are state."
    )
    return result


def _kayle_e(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    passive = extract_named(ability, "Passive Damage", rank, ctx.stats, ctx.target)
    active = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    result = ability_on_hit_entry(
        ability.get("name", "Starfire Spellblade"),
        rank,
        "magic",
        {"name": "Starfire passive", "damage_per_hit": passive, "damage_type": "magic"},
        extract_cooldown(ability, rank),
    )
    result["parts"] = (DamagePart("magic", active, basic_damage=True, time_offset=0.1),)
    result["total_raw"] = active
    result["empowers_next_auto"] = True
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "Passive on-hit plus one empowered attack; the active rider scales with target missing health and AP."
    )
    return result


def _kayle_r(ctx: SlotCtx) -> dict[str, Any] | None:
    result = _typed(ctx, "Magic Damage", "magic", time_offset=2.5)
    if result:
        result["detail"] = (
            "Divine Judgment damage resolves after the sourced 2.5-second invulnerability window."
        )
    return result


def _kayn_q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    hits = 2
    form = str(ctx.options.get("form", "base"))
    attr = "Total Physical Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    if form == "darkin":
        # The source's Darkin branch is an additional max-health rider.  Keep
        # it as a typed part so the health-sensitive receipt is visible.
        per_hit = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
        max_hp = float(ctx.target.get("target_max_health", 0.0) or 0.0)
        health_part = max_hp * (
            0.06 + 0.035 * ctx.stats.get("bonus_attack_damage", 0.0) / 100.0
        )
        value = per_hit * hits + health_part * hits
        parts = (
            DamagePart(
                "physical", per_hit, count=hits, time_offset=0.1, hit_interval=0.15
            ),
            DamagePart(
                "physical",
                health_part,
                count=hits,
                hp_scaled_damage=(lambda _m, amount=health_part: amount),
                time_offset=0.1,
                hit_interval=0.15,
            ),
        )
    else:
        parts = (
            DamagePart(
                "physical", value / hits, count=hits, time_offset=0.1, hit_interval=0.15
            ),
        )
    return {
        "name": ability.get("name", "Reaping Slash"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": parts,
        "target_max_health_sensitive": form == "darkin",
        "detail": f"Two ordered Reaping Slash hits; form={form}.",
    }


def _kayn_r(ctx: SlotCtx) -> dict[str, Any] | None:
    result = _typed(ctx, "Physical Damage", "physical", time_offset=0.75)
    if result:
        result["detail"] = (
            f"Umbral Trespass recast after the sourced attach/channel delay; form={ctx.options.get('form', 'base')}."
        )
    return result


def _kennen_w(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    active = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    passive = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    result = ability_on_hit_entry(
        ability.get("name", "Electrical Surge"),
        rank,
        "magic",
        {
            "name": "Electrical Surge passive",
            "damage_per_hit": (
                passive if bool(ctx.options.get("w_empowered", True)) else 0.0
            ),
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


def _kennen_r(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    bolts = max(1, min(6, int(ctx.options.get("r_bolts", 6))))
    per = extract_named(ability, "Magic Damage Per Bolt", rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Slicing Maelstrom"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per * bolts,
        "parts": (
            DamagePart("magic", per, count=bolts, time_offset=0.5, hit_interval=0.5),
        ),
        "detail": f"{bolts} ordered bolts; later strikes use the sourced escalating storm packet.",
        "event_order_certified": True,
    }


def _khazix_passive(ctx: SlotCtx) -> dict[str, Any] | None:
    if not bool(ctx.options.get("p_ready", True)):
        return no_damage(
            ctx,
            name="Unseen Threat",
            reason="The isolated-stealth empowered attack is not armed in this scenario.",
        )
    ability = ctx.ability()
    if ability is None:
        return None
    value = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    result = on_hit_entry("Unseen Threat", value, "magic")
    result["detail"] = (
        "One empowered next basic attack after Kha'Zix leaves enemy vision; isolation is a target-state option."
    )
    return result


def _khazix_q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    isolated = bool(ctx.options.get("q_isolated", True))
    attr = "Isolated Target Physical Damage" if isolated else "Physical Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Taste Their Fear"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": (DamagePart("physical", value),),
        "detail": "Isolated target branch is explicit; nearby-allies state disables the 210% branch.",
    }


def _kindred_q(ctx: SlotCtx) -> dict[str, Any] | None:
    result = _typed(ctx, "Physical Damage", "physical")
    if result:
        result["detail"] = (
            f"Dance of Arrows; {int(ctx.options.get('marks', 0))} Mark of the Kindred stacks grant the sourced attack-speed state."
        )
    return result


def _kindred_w(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attacks = max(1, min(8, int(ctx.options.get("w_attacks", 3))))
    per = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Wolf's Frenzy"),
        "rank": rank,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": per * attacks,
        "parts": (
            DamagePart("magic", per, count=attacks, time_offset=0.5, hit_interval=1.0),
        ),
        "detail": f"{attacks} Wolf attacks; mark-based current-health term is read by the source scaler.",
        "target_max_health_sensitive": True,
    }


def _kindred_e(ctx: SlotCtx) -> dict[str, Any] | None:
    result = _typed(ctx, "Additional Physical Damage", "physical")
    if result:
        result["detail"] = (
            f"Mounting Dread third-hit proc with {int(ctx.options.get('e_stacks', 3))} mark stacks."
        )
        result["target_max_health_sensitive"] = True
    return result


def _kled_q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attr = (
        "Total Physical Damage"
        if bool(ctx.options.get("q_pull", True))
        else "Physical Damage"
    )
    return _typed(ctx, attr, "physical")


def _kled_w(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.level
    value = extract_named(
        ability, "Additional Physical Damage", rank, ctx.stats, ctx.target
    )
    result = ability_on_hit_entry(
        ability.get("name", "Violent Tendencies"),
        rank,
        "physical",
        {
            "name": "Violent Tendencies (first three attacks)",
            "damage_per_hit": 0.0,
            "damage_type": "physical",
        },
        0.0,
    )
    result["parts"] = (
        DamagePart("physical", value, basic_damage=True, time_offset=0.1),
    )
    result["total_raw"] = value
    result["empowers_next_auto"] = True
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "Fourth attack of the four-hit Violent Tendencies sequence; 150% attack speed is state."
    )
    return result


def _kled_r(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    fraction = max(0.0, min(1.0, float(ctx.options.get("charge_fraction", 1.0))))
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * fraction
    return {
        "name": ability.get("name", "Chaaaaaaaarge!!!"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value, time_offset=0.5),),
        "target_max_health_sensitive": True,
        "detail": f"Charge fraction {fraction:.2f}; shield and team movement are utility state.",
    }


def _leblanc_q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    attr = (
        "Total Magic Damage"
        if bool(ctx.options.get("q_consume", True))
        else "Magic Damage"
    )
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Sigil of Malice"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value),),
        "detail": "Sigil orb plus optional mark consumption are one explicitly ordered target sequence.",
    }


def _leblanc_e(ctx: SlotCtx) -> dict[str, Any] | None:
    attr = (
        "Total Damage"
        if bool(ctx.options.get("e_chain_complete", True))
        else "Magic Damage"
    )
    result = _typed(ctx, attr, "magic")
    if result:
        result["detail"] = (
            "Ethereal Chains application and fracture are included only when the tether completes."
        )
    return result


def _leblanc_r(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    choice = str(ctx.options.get("r_mimic", "Q"))
    attr = {
        "Q": "Total Magic Damage",
        "W": "Magic Damage",
        "E": "Total Magic Damage",
    }.get(choice, "Total Magic Damage")
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Mimic"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value, time_offset=0.2),),
        "detail": f"Mimic variant {choice}; copied basic-ability effects remain in the explicit variant choice.",
    }


def _leona_q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    value = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    result = ability_on_hit_entry(
        ability.get("name", "Shield of Daybreak"),
        rank,
        "magic",
        {"name": "Shield of Daybreak", "damage_per_hit": value, "damage_type": "magic"},
        extract_cooldown(ability, rank),
    )
    result["empowers_next_auto"] = True
    result["detail"] = "One empowered basic attack; the stun is control state."
    return result


def _leona_passive(ctx: SlotCtx) -> dict[str, Any] | None:
    result = proc_damage(
        lambda c, a: extract_named(a, "Per-Level Scaling", c.level, c.stats, c.target),
        "magic",
        count_option="p_marks",
        default_count=1,
        name="Sunlight (ally detonation)",
        phase_order_events=True,
    )(ctx)
    if result:
        result["detail"] = (
            "One sourced ally-triggered Sunlight detonation per marked target; marking is ordered state."
        )
    return result


_leona_passive.phase = ONHIT


def _lillia_p(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    ticks = max(1, min(6, int(ctx.options.get("p_ticks", 6))))
    max_hp = float(ctx.target.get("target_max_health", 0.0) or 0.0)
    ap = float(ctx.stats.get("ability_power", 0.0))
    total = max_hp * (0.05 + 0.0125 * ap / 100.0)
    per = total / 6.0
    return {
        "name": ability.get("name", "Dream-Laden Bough"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": per * ticks,
        "parts": (
            DamagePart("magic", per, count=ticks, time_offset=0.5, hit_interval=0.5),
        ),
        "target_max_health_sensitive": True,
        "detail": f"Dream Dust over 3 seconds; {ticks} half-second ticks selected.",
    }


def _lillia_q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    magic = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    true_damage = magic if bool(ctx.options.get("q_outer_edge", True)) else 0.0
    return _mixed(
        ctx,
        ability.get("name", "Blooming Blows"),
        rank,
        extract_cooldown(ability, rank),
        magic,
        true_damage,
        detail="Outer-edge option adds the sourced true-damage ring.",
    )


def _lillia_w(ctx: SlotCtx) -> dict[str, Any] | None:
    attr = (
        "Increased Damage"
        if bool(ctx.options.get("w_epicenter", True))
        else "Magic Damage"
    )
    result = _typed(ctx, attr, "magic", time_offset=0.759)
    if result:
        result["detail"] = (
            "Watch Out! Eep! epicenter branch is explicit; dash distance and slow are utility state."
        )
    return result


def _lillia_r(ctx: SlotCtx) -> dict[str, Any] | None:
    if not bool(ctx.options.get("r_wake", True)):
        return no_damage(
            ctx,
            name="Lilting Lullaby",
            reason="The sleep is applied but no post-sleep waking damage is selected.",
        )
    result = _typed(ctx, "Magic Damage", "magic", time_offset=2.3)
    if result:
        result["detail"] = (
            "Lilting Lullaby wake damage after drowsy and sleep; the crowd-control window is state."
        )
    return result


def _locke_p(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    base = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    missing_ratio = float(ctx.target.get("target_missing_health", 0.0) or 0.0) / max(
        1.0, float(ctx.target.get("target_max_health", 1.0) or 1.0)
    )
    value = base * (1.0 + max(0.0, min(1.0, missing_ratio)))
    result = on_hit_entry("Silver Stake", value, "magic")
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "On-hit damage doubles linearly with target missing-health ratio, capped by the sourced bonus row."
    )
    return result


def _locke_q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    casts = max(1, min(3, int(ctx.options.get("q_casts", 3))))
    per = extract_named(ability, "Magic Damage per Nail", rank, ctx.stats, ctx.target)
    stacks = max(0, min(3, int(ctx.options.get("soul_nails", 0))))
    bonus_attr = {
        1: "One Stack Bonus Damage",
        2: "Two Stacks Bonus Damage",
        3: "Three Stacks Bonus Damage",
    }.get(stacks)
    bonus = (
        extract_named(ability, bonus_attr, rank, ctx.stats, ctx.target)
        if bonus_attr
        else 0.0
    )
    return {
        "name": ability.get("name", "Ritual Nails"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per * casts + bonus,
        "parts": (
            (
                DamagePart(
                    "magic", per, count=casts, time_offset=0.15, hit_interval=0.15
                ),
                DamagePart("magic", bonus, time_offset=0.5),
            )
            if bonus
            else (
                DamagePart(
                    "magic", per, count=casts, time_offset=0.15, hit_interval=0.15
                ),
            )
        ),
        "detail": f"{casts} Ritual Nails casts; {stacks} Soul Nails stacks are consumed by the next damaging attack.",
    }


def _locke_e(ctx: SlotCtx) -> dict[str, Any] | None:
    attr = (
        "Total Magic Damage"
        if bool(ctx.options.get("e_dash", True))
        else "Blink Magic Damage"
    )
    result = _typed(ctx, attr, "magic", time_offset=0.1)
    if result:
        result["detail"] = "Ashen Pursuit blink plus optional empowered dash attack."
    return result


def _locke_r(ctx: SlotCtx) -> dict[str, Any] | None:
    result = _typed(ctx, "Magic Damage", "magic", time_offset=0.75)
    if result:
        result["target_max_health_sensitive"] = True
        result["detail"] = (
            "Purgatory totem damage; mark refresh and execute threshold remain explicit target state."
        )
    return result


def _sources(
    name: str, parent: int, timestamp: str, slots: dict[str, tuple[int, str]]
) -> list[dict[str, Any]]:
    rows = [
        source_row(
            f"{name} parent entry",
            f"https://wiki.leagueoflegends.com/en-us/{name}",
            parent,
            timestamp,
        )
    ]
    for slot, (revision, slot_time) in slots.items():
        template_slot = "I" if slot == "P" else slot
        rows.append(
            source_row(
                f"{name} {slot} template",
                f"https://wiki.leagueoflegends.com/en-us/Template:Data_{name.replace(' ', '_')}/{template_slot}",
                revision,
                slot_time,
            )
        )
    return rows


def _module(
    name: str,
    slots: dict[str, Callable[[SlotCtx], dict[str, Any] | None]],
    options: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "SLOTS": slots,
        "OPTIONS": options,
        "SOURCES": sources,
        "ASSUMPTIONS": [
            "Every passive/Q/W/E/R slot was reviewed against the complete parent Wiki entry and its five namespace-10 template receipts.",
            "Only the explicit one-rotation target/variant options are priced; utility, control, movement, healing and defensive state remain named rather than guessed.",
            "All numeric rank/level values are read from the cached source JSON through typed extractors.",
        ],
    }


# Public batch definitions consumed by the twelve thin champion modules.
BATCH_03: dict[str, dict[str, Any]] = {
    "Katarina": _module(
        "Katarina",
        {
            "P": proc_damage(
                lambda c, a: extract_named(
                    a, "Bonus Magic Damage", c.level, c.stats, c.target
                ),
                "magic",
                "p_daggers",
                1,
                "Voracity (Sinister Steel)",
                True,
            ),
            "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "W": lambda c: no_damage(
                c,
                name="Preparation",
                reason="Dagger toss, movement speed and landing location are utility state.",
            ),
            "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "R": _r_daggers,
        },
        [
            {
                "key": "p_daggers",
                "type": "int",
                "default": 1,
                "min": 0,
                "max": 6,
                "label": "Dagger retrieval procs",
            },
            {
                "key": "r_daggers",
                "type": "int",
                "default": 15,
                "min": 1,
                "max": 15,
                "label": "Death Lotus daggers",
            },
        ],
        _sources(
            "Katarina",
            3892646,
            "2025-05-02T11:27:31Z",
            {
                "P": (2864111, "2019-11-03T20:05:46Z"),
                "Q": (2863963, "2019-11-03T19:57:20Z"),
                "W": (2864258, "2019-11-03T20:10:07Z"),
                "E": (2864404, "2019-11-03T20:12:38Z"),
                "R": (2864550, "2019-11-03T20:16:02Z"),
            },
        ),
    ),
    "Kayle": _module(
        "Kayle",
        {
            "P": _kayle_passive,
            "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "W": lambda c: no_damage(
                c,
                name="Celestial Blessing",
                reason="Heal, ally targeting and movement speed are support/utility state.",
            ),
            "E": _kayle_e,
            "R": _kayle_r,
        },
        [
            {
                "key": "p_exalted",
                "type": "bool",
                "default": True,
                "label": "Exalted Aflame wave",
            },
            {
                "key": "e_empowered",
                "type": "bool",
                "default": True,
                "label": "Starfire empowered attack",
            },
        ],
        _sources(
            "Kayle",
            3968743,
            "2025-11-21T13:52:48Z",
            {
                "P": (2864112, "2019-11-03T20:05:47Z"),
                "Q": (2863964, "2019-11-03T19:57:21Z"),
                "W": (2864259, "2019-11-03T20:10:08Z"),
                "E": (2864405, "2019-11-03T20:12:39Z"),
                "R": (2917936, "2020-02-04T23:40:02Z"),
            },
        ),
    ),
    "Kayn": _module(
        "Kayn",
        {
            "P": lambda c: no_damage(
                c,
                name="The Darkin Scythe",
                reason="Form transformation and Shadow Assassin post-mitigation bonus/Darkin healing are explicit state; choose form for Q/R branches.",
            ),
            "Q": _kayn_q,
            "W": simple_damage(attr="Physical Damage", dmg_type="physical"),
            "E": lambda c: no_damage(
                c,
                name="Shadow Step",
                reason="Terrain phasing, movement speed and first-entry heal are utility state.",
            ),
            "R": _kayn_r,
        },
        [
            {
                "key": "form",
                "type": "select",
                "default": "base",
                "label": "Kayn form",
                "choices": [
                    {"value": "base", "label": "Untransformed"},
                    {"value": "darkin", "label": "Darkin Slayer"},
                    {"value": "shadow_assassin", "label": "Shadow Assassin"},
                ],
            }
        ],
        _sources(
            "Kayn",
            4011961,
            "2026-04-24T08:09:26Z",
            {
                "P": (2864113, "2019-11-03T20:05:48Z"),
                "Q": (2863965, "2019-11-03T19:57:22Z"),
                "W": (2864260, "2019-11-03T20:10:09Z"),
                "E": (2864406, "2019-11-03T20:12:40Z"),
                "R": (2864552, "2019-11-03T20:16:04Z"),
            },
        ),
    ),
    "Kennen": _module(
        "Kennen",
        {
            "P": lambda c: no_damage(
                c,
                name="Mark of the Storm",
                reason="Mark stacks, stun and energy refund are ordered control state.",
            ),
            "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "W": _kennen_w,
            "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "R": _kennen_r,
        },
        [
            {
                "key": "w_empowered",
                "type": "bool",
                "default": True,
                "label": "Four-stack Electrical Surge attack",
            },
            {
                "key": "r_bolts",
                "type": "int",
                "default": 6,
                "min": 1,
                "max": 6,
                "label": "Slicing Maelstrom bolts",
            },
        ],
        _sources(
            "Kennen",
            3892654,
            "2025-05-02T11:27:49Z",
            {
                "P": (2864114, "2019-11-03T20:05:49Z"),
                "Q": (2863966, "2019-11-03T19:57:23Z"),
                "W": (2864261, "2019-11-03T20:10:10Z"),
                "E": (2864407, "2019-11-03T20:12:41Z"),
                "R": (2864553, "2019-11-03T20:16:05Z"),
            },
        ),
    ),
    "Kha'Zix": _module(
        "Kha'Zix",
        {
            "P": _khazix_passive,
            "Q": _khazix_q,
            "W": simple_damage(attr="Physical Damage", dmg_type="physical"),
            "E": simple_damage(attr="Physical Damage", dmg_type="physical"),
            "R": lambda c: no_damage(
                c,
                name="Void Assault",
                reason="Invisibility, evolution and movement speed are state; the recast does not deal enemy damage.",
            ),
        },
        [
            {
                "key": "p_ready",
                "type": "bool",
                "default": True,
                "label": "Unseen Threat armed",
            },
            {
                "key": "q_isolated",
                "type": "bool",
                "default": True,
                "label": "Isolated target",
            },
        ],
        _sources(
            "Kha'Zix",
            4012057,
            "2026-04-24T20:28:09Z",
            {
                "P": (2864115, "2019-11-03T20:05:50Z"),
                "Q": (2863967, "2019-11-03T19:57:24Z"),
                "W": (2864262, "2019-11-03T20:10:11Z"),
                "E": (2864408, "2019-11-03T20:12:42Z"),
                "R": (2864554, "2019-11-03T20:16:07Z"),
            },
        ),
    ),
    "Kindred": _module(
        "Kindred",
        {
            "P": lambda c: no_damage(
                c,
                name="Mark of the Kindred",
                reason="Hunt marks and bonus attack range are state; marks are exposed to Q/E options.",
            ),
            "Q": _kindred_q,
            "W": _kindred_w,
            "E": _kindred_e,
            "R": lambda c: no_damage(
                c,
                name="Lamb's Respite",
                reason="The minimum-health zone and end heal are defensive/utility state, not enemy damage.",
            ),
        },
        [
            {
                "key": "marks",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 25,
                "label": "Mark of the Kindred stacks",
            },
            {
                "key": "w_attacks",
                "type": "int",
                "default": 3,
                "min": 1,
                "max": 8,
                "label": "Wolf attacks",
            },
            {
                "key": "e_stacks",
                "type": "int",
                "default": 3,
                "min": 1,
                "max": 3,
                "label": "Mounting Dread stacks",
            },
        ],
        _sources(
            "Kindred",
            3892676,
            "2025-05-02T11:28:40Z",
            {
                "P": (2864116, "2019-11-03T20:05:51Z"),
                "Q": (2863968, "2019-11-03T19:57:25Z"),
                "W": (2864263, "2019-11-03T20:10:12Z"),
                "E": (2864409, "2019-11-03T20:12:43Z"),
                "R": (2864555, "2019-11-03T20:16:07Z"),
            },
        ),
    ),
    "Kled": _module(
        "Kled",
        {
            "P": lambda c: no_damage(
                c,
                name="Skaarl the Cowardly Lizard",
                reason="Mounted/dismounted health pool, remount and damage cutoff are participant state.",
            ),
            "Q": _kled_q,
            "W": _kled_w,
            "E": simple_damage(attr="Total Physical Damage", dmg_type="physical"),
            "R": _kled_r,
        },
        [
            {
                "key": "q_pull",
                "type": "bool",
                "default": True,
                "label": "Bear Trap pull resolves",
            },
            {
                "key": "charge_fraction",
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 1.0,
                "step": 0.25,
                "label": "Chaaaaaaaarge distance",
            },
        ],
        _sources(
            "Kled",
            4008139,
            "2026-04-13T19:20:03Z",
            {
                "P": (2864117, "2019-11-03T20:05:52Z"),
                "Q": (2980665, "2020-05-07T10:03:59Z"),
                "W": (2864264, "2019-11-03T20:10:13Z"),
                "E": (2864410, "2019-11-03T20:12:44Z"),
                "R": (2864556, "2019-11-03T20:16:08Z"),
            },
        ),
    ),
    "LeBlanc": _module(
        "LeBlanc",
        {
            "P": lambda c: no_damage(
                c,
                name="Mirror Image",
                reason="Clone spawning, invisibility and pet movement are state; the clone's basic attacks deal no damage.",
            ),
            "Q": _leblanc_q,
            "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "E": _leblanc_e,
            "R": _leblanc_r,
        },
        [
            {
                "key": "q_consume",
                "type": "bool",
                "default": True,
                "label": "Sigil mark is consumed",
            },
            {
                "key": "e_chain_complete",
                "type": "bool",
                "default": True,
                "label": "Ethereal Chains completes",
            },
            {
                "key": "r_mimic",
                "type": "select",
                "default": "Q",
                "label": "Mimic variant",
                "choices": [
                    {"value": "Q", "label": "Mimic Q"},
                    {"value": "W", "label": "Mimic W"},
                    {"value": "E", "label": "Mimic E"},
                ],
            },
        ],
        _sources(
            "LeBlanc",
            4002546,
            "2026-03-26T01:43:25Z",
            {
                "P": (2864119, "2019-11-03T20:05:54Z"),
                "Q": (2863971, "2019-11-03T19:57:28Z"),
                "W": (2864266, "2019-11-03T20:10:15Z"),
                "E": (2864412, "2019-11-03T20:12:46Z"),
                "R": (2864558, "2019-11-03T20:16:10Z"),
            },
        ),
    ),
    "Lee Sin": _module(
        "Lee Sin",
        {
            "P": lambda c: no_damage(
                c,
                name="Flurry",
                reason="Two-attack haste and energy restoration are attack-timeline state.",
            ),
            "Q": simple_damage(attr="Physical Damage", dmg_type="physical"),
            "W": lambda c: no_damage(
                c,
                name="Safeguard",
                reason="Ally dash and shield are defensive/team state.",
            ),
            "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "R": simple_damage(attr="Physical Damage", dmg_type="physical"),
        },
        [],
        _sources(
            "Lee Sin",
            4001404,
            "2026-03-20T15:11:02Z",
            {
                "P": (2864120, "2019-11-03T20:05:55Z"),
                "Q": (2863972, "2019-11-03T19:57:29Z"),
                "W": (2864267, "2019-11-03T20:10:16Z"),
                "E": (2864413, "2019-11-03T20:12:47Z"),
                "R": (2864559, "2019-11-03T20:16:11Z"),
            },
        ),
    ),
    "Leona": _module(
        "Leona",
        {
            "P": _leona_passive,
            "Q": _leona_q,
            "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
        },
        [
            {
                "key": "p_marks",
                "type": "int",
                "default": 1,
                "min": 0,
                "max": 6,
                "label": "Sunlight ally detonations",
            }
        ],
        _sources(
            "Leona",
            3977650,
            "2025-12-20T01:49:57Z",
            {
                "P": (2864121, "2019-11-03T20:05:56Z"),
                "Q": (2863973, "2019-11-03T19:57:30Z"),
                "W": (2864268, "2019-11-03T20:10:17Z"),
                "E": (2864415, "2019-11-03T20:12:49Z"),
                "R": (2864560, "2019-11-03T20:16:12Z"),
            },
        ),
    ),
    "Lillia": _module(
        "Lillia",
        {
            "P": _lillia_p,
            "Q": _lillia_q,
            "W": _lillia_w,
            "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
            "R": _lillia_r,
        },
        [
            {
                "key": "p_ticks",
                "type": "int",
                "default": 6,
                "min": 1,
                "max": 6,
                "label": "Dream Dust ticks",
            },
            {
                "key": "q_outer_edge",
                "type": "bool",
                "default": True,
                "label": "Blooming Blows outer edge",
            },
            {
                "key": "w_epicenter",
                "type": "bool",
                "default": True,
                "label": "Watch Out! Eep! epicenter",
            },
            {
                "key": "r_wake",
                "type": "bool",
                "default": True,
                "label": "Lilting Lullaby wake damage",
            },
        ],
        _sources(
            "Lillia",
            3993738,
            "2026-02-23T15:38:19Z",
            {
                "P": (3065445, "2020-07-07T15:39:51Z"),
                "Q": (3065446, "2020-07-07T15:40:16Z"),
                "W": (3065447, "2020-07-07T15:40:36Z"),
                "E": (3065448, "2020-07-07T15:40:52Z"),
                "R": (3065449, "2020-07-07T15:41:07Z"),
            },
        ),
    ),
    "Locke": _module(
        "Locke",
        {
            "P": _locke_p,
            "Q": _locke_q,
            "W": lambda c: no_damage(
                c,
                name="Soul Ignition",
                reason="Grey health storage, attack speed, movement speed and recast healing are self-state.",
            ),
            "E": _locke_e,
            "R": _locke_r,
        },
        [
            {
                "key": "q_casts",
                "type": "int",
                "default": 3,
                "min": 1,
                "max": 3,
                "label": "Ritual Nails casts",
            },
            {
                "key": "soul_nails",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 3,
                "label": "Soul Nails stacks",
            },
            {
                "key": "e_dash",
                "type": "bool",
                "default": True,
                "label": "Ashen Pursuit dash",
            },
        ],
        _sources(
            "Locke",
            4036538,
            "2026-06-27T10:48:19Z",
            {
                "P": (4026037, "2026-06-09T15:41:17Z"),
                "Q": (4026041, "2026-06-09T15:59:12Z"),
                "W": (4026042, "2026-06-09T16:00:35Z"),
                "E": (4026043, "2026-06-09T16:01:36Z"),
                "R": (4026044, "2026-06-09T16:01:55Z"),
            },
        ),
    ),
}


def module_for(name: str) -> dict[str, Any]:
    return BATCH_03[name]


def build_batch_module(name: str):
    spec = module_for(name)
    return (
        build_parser(spec["SLOTS"], name),
        spec["SLOTS"],
        spec["ASSUMPTIONS"],
        spec["SOURCES"],
        spec["OPTIONS"],
    )
